"""Tests for the protocol helpers and the defaults wired on top of them."""

import json
import logging

import pytest

from econagents.core.events import Message
from econagents.core.game_runner import TurnBasedGameRunnerConfig
from econagents.core.manager.phase import TurnBasedPhaseManager, HybridPhaseManager
from econagents.core.protocol import (
    INTRODUCTION_PHASE,
    build_message,
    join_message,
    ready_message,
)
from econagents.core.transport import JoinPayloadAuth


class TestBuildMessage:
    """Tests for the outbound envelope builder."""

    def test_minimal(self):
        assert build_message("ready") == {"meta": {"type": "ready"}, "payload": {}}

    def test_with_payload(self):
        msg = build_message("submit-choice", payload={"choice": "COOPERATE"})
        assert msg == {"meta": {"type": "submit-choice"}, "payload": {"choice": "COOPERATE"}}

    def test_string_component_is_expanded(self):
        msg = build_message("submit-choice", payload={"choice": "DEFECT"}, component="standard:coordination")
        assert msg["meta"]["component"] == {"type": "standard:coordination"}

    def test_dict_component_passed_through(self):
        component = {"type": "standard:coordination", "instance": "abc"}
        msg = build_message("submit-choice", component=component)
        assert msg["meta"]["component"] == component

    def test_join_message(self):
        assert join_message(recovery="CODE1") == {"meta": {"type": "join"}, "payload": {"recovery": "CODE1"}}

    def test_ready_message(self):
        assert ready_message() == {"meta": {"type": "ready", "component": {"type": "standard:ready"}}, "payload": {}}


class _FakeTransport:
    """Minimal transport stand-in that records the messages it is asked to send."""

    def __init__(self):
        self.sent: list[str] = []

    async def send(self, message: str):
        self.sent.append(message)


class TestJoinPayloadAuth:
    """Tests for the default authentication mechanism."""

    @pytest.mark.asyncio
    async def test_wraps_kwargs_into_join_envelope(self):
        transport = _FakeTransport()
        ok = await JoinPayloadAuth().authenticate(transport, recovery="CODE1")
        assert ok is True
        assert json.loads(transport.sent[0]) == {"meta": {"type": "join"}, "payload": {"recovery": "CODE1"}}

    @pytest.mark.asyncio
    async def test_full_envelope_passed_through(self):
        transport = _FakeTransport()
        envelope = {"meta": {"type": "join"}, "payload": {"recovery": "CODE2"}}
        await JoinPayloadAuth().authenticate(transport, **envelope)
        assert json.loads(transport.sent[0]) == envelope


class TestDefaultIntroductionHandler:
    """The phase managers should ready-up automatically during introduction."""

    @pytest.mark.parametrize("manager_cls", [TurnBasedPhaseManager, HybridPhaseManager])
    @pytest.mark.asyncio
    async def test_introduction_handler_returns_ready(self, manager_cls):
        manager = manager_cls(logger=logging.getLogger("test_protocol"))
        assert INTRODUCTION_PHASE in manager._phase_handlers
        result = await manager._phase_handlers[INTRODUCTION_PHASE](INTRODUCTION_PHASE, manager.state)
        assert result == ready_message()

    @pytest.mark.asyncio
    async def test_introduction_handler_is_overridable(self):
        manager = TurnBasedPhaseManager(logger=logging.getLogger("test_protocol"))

        async def custom(phase, state):
            return {"meta": {"type": "ready"}, "payload": {"custom": True}}

        manager.register_phase_handler(INTRODUCTION_PHASE, custom)
        result = await manager._phase_handlers[INTRODUCTION_PHASE](INTRODUCTION_PHASE, manager.state)
        assert result == {"meta": {"type": "ready"}, "payload": {"custom": True}}


class TestRunnerConfigDefaults:
    """The runner config should default to the join handshake."""

    def test_default_auth_mechanism_is_join(self):
        config = TurnBasedGameRunnerConfig(hostname="localhost", port=3000, path="", game_id=1)
        assert isinstance(config.auth_mechanism, JoinPayloadAuth)


class TestResolvePlayerNumber:
    """The manager resolves the agent's player number from the players list."""

    def _manager(self, recovery):
        from econagents.core.state.game import GameState

        return TurnBasedPhaseManager(
            logger=logging.getLogger("test_protocol"),
            state=GameState(),
            auth_mechanism_kwargs={"recovery": recovery},
        )

    @pytest.mark.asyncio
    async def test_resolves_from_players_list(self):
        manager = self._manager("r2")
        msg = Message(
            message_type="event",
            event_type="snapshot",
            data={"players": [{"playerNumber": 1, "recovery": "r1"}, {"playerNumber": 2, "recovery": "r2"}]},
        )
        await manager._resolve_player_number(msg)
        assert manager.state.meta.player_number == 2

    @pytest.mark.asyncio
    async def test_noop_without_match_or_recovery(self):
        manager = self._manager("missing")
        await manager._resolve_player_number(
            Message(message_type="event", event_type="snapshot", data={"players": [{"playerNumber": 1, "recovery": "r1"}]})
        )
        assert manager.state.meta.player_number is None

        # An event with no players list is a no-op too.
        await manager._resolve_player_number(Message(message_type="event", event_type="phase-transition", data={}))
        assert manager.state.meta.player_number is None

    @pytest.mark.asyncio
    async def test_runs_via_global_event_handler(self):
        manager = self._manager("r1")
        await manager.on_event(
            Message(message_type="event", event_type="snapshot", data={"players": [{"playerNumber": 1, "recovery": "r1"}]})
        )
        assert manager.state.meta.player_number == 1
