"""Tests for the protocol helpers and the defaults wired on top of them."""

import json

import pytest

from econagents.runtime import Agent
from econagents.runtime.game_runner import TurnBasedGameRunnerConfig
from econagents.adapters.protocol import (
    INTRODUCTION_PHASE,
    build_message,
    join_message,
    ready_message,
)
from econagents.domain.state.game import GameState
from econagents.adapters.transport import JoinPayloadAuth
from econagents.domain import Event
from tests.runtime.test_agent import FakeTransport
from tests.conftest import MockRole


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
    """Agents ready-up during introduction."""

    @pytest.mark.asyncio
    async def test_introduction_handler_sends_ready(self, tmp_path):
        transport = FakeTransport()
        agent = Agent(
            url="ws://localhost:8765",
            state=GameState(),
            role=MockRole(),
            prompts_dir=tmp_path,
            transport=transport,
        )

        await agent.handle_phase_transition(INTRODUCTION_PHASE)

        assert json.loads(transport.sent[0]) == ready_message()

    @pytest.mark.asyncio
    async def test_introduction_handler_is_overridable(self, tmp_path):
        transport = FakeTransport()
        agent = Agent(
            url="ws://localhost:8765",
            state=GameState(),
            role=MockRole(),
            prompts_dir=tmp_path,
            transport=transport,
        )

        async def custom(phase, state):
            return {"meta": {"type": "ready"}, "payload": {"custom": True}}

        agent.register_phase_handler(INTRODUCTION_PHASE, custom)
        await agent.handle_phase_transition(INTRODUCTION_PHASE)

        assert json.loads(transport.sent[0]) == {"meta": {"type": "ready"}, "payload": {"custom": True}}


class TestRunnerConfigDefaults:
    """The runner config should default to the join handshake."""

    def test_default_auth_mechanism_is_join(self):
        config = TurnBasedGameRunnerConfig(hostname="localhost", port=3000, path="", game_id=1)
        assert isinstance(config.auth_mechanism, JoinPayloadAuth)


class TestResolvePlayerNumber:
    """The agent resolves its player number from the players list."""

    def _agent(self, recovery, tmp_path):
        return Agent(
            url="ws://localhost:8765",
            state=GameState(),
            role=MockRole(),
            prompts_dir=tmp_path,
            auth_mechanism_kwargs={"recovery": recovery},
            transport=FakeTransport(),
        )

    @pytest.mark.asyncio
    async def test_resolves_from_players_list(self, tmp_path):
        agent = self._agent("r2", tmp_path)
        agent._resolve_player_number(
            Event(
                type="snapshot",
                data={"players": [{"playerNumber": 1, "recovery": "r1"}, {"playerNumber": 2, "recovery": "r2"}]},
            )
        )
        assert agent.state.meta.player_number == 2

    @pytest.mark.asyncio
    async def test_noop_without_match_or_recovery(self, tmp_path):
        agent = self._agent("missing", tmp_path)
        agent._resolve_player_number(Event(type="snapshot", data={"players": [{"playerNumber": 1, "recovery": "r1"}]}))
        assert agent.state.meta.player_number is None

        agent._resolve_player_number(Event(type="phase-transition", data={}))
        assert agent.state.meta.player_number is None

    @pytest.mark.asyncio
    async def test_runs_during_event_handling(self, tmp_path):
        agent = self._agent("r1", tmp_path)
        await agent.on_event(Event(type="snapshot", data={"players": [{"playerNumber": 1, "recovery": "r1"}]}))
        assert agent.state.meta.player_number == 1
