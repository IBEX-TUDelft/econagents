import asyncio
import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from econagents.runtime import Agent, PhaseEngine
from econagents.domain.role import Role
from econagents.adapters.protocol import INTRODUCTION_PHASE
from econagents.domain.state.game import GameState
from econagents.domain import Event


class FakeTransport:
    def __init__(self):
        self.sent: list[str] = []
        self.started = False
        self.stopped = False

    async def start_listening(self) -> None:
        self.started = True

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def stop(self) -> None:
        self.stopped = True


@pytest.fixture
def role():
    role = MagicMock(spec=Role)
    role.name = "test_role"
    role.handle_phase = AsyncMock(return_value={"meta": {"type": "choose"}, "payload": {"choice": "A"}})
    return role


@pytest.mark.asyncio
async def test_agent_projects_state_and_sends_role_action(role, tmp_path: Path):
    transport = FakeTransport()
    state = GameState()
    agent = Agent(
        url="ws://localhost:8765",
        state=state,
        role=role,
        prompts_dir=tmp_path,
        transport=transport,
    )

    await agent.on_event(Event(type="phase-transition", data={"phase": "decision"}))

    assert state.meta.phase == "decision"
    role.handle_phase.assert_called_once_with("decision", state, tmp_path)
    assert json.loads(transport.sent[-1]) == {"meta": {"type": "choose"}, "payload": {"choice": "A"}}


@pytest.mark.asyncio
async def test_agent_sends_ready_during_introduction(role, tmp_path: Path):
    transport = FakeTransport()
    agent = Agent(
        url="ws://localhost:8765",
        state=GameState(),
        role=role,
        prompts_dir=tmp_path,
        transport=transport,
    )

    await agent.handle_phase_transition(INTRODUCTION_PHASE)

    role.handle_phase.assert_not_called()
    assert json.loads(transport.sent[-1]) == {
        "meta": {"type": "ready", "component": {"type": "standard:ready"}},
        "payload": {},
    }


@pytest.mark.asyncio
async def test_agent_stops_on_end_game_event(role, tmp_path: Path):
    transport = FakeTransport()
    agent = Agent(
        url="ws://localhost:8765",
        state=GameState(),
        role=role,
        prompts_dir=tmp_path,
        transport=transport,
    )
    agent.running = True

    await agent.on_event(Event(type="game-over", data={}))

    assert agent.running is False
    assert transport.stopped is True


@pytest.mark.asyncio
async def test_continuous_loop_logs_action_error_and_keeps_deciding(role, tmp_path: Path, caplog):
    transport = FakeTransport()
    calls = 0

    async def flaky(phase, state, prompts_dir):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("provider outage")
        return {"meta": {"type": "bid"}, "payload": {}}

    role.handle_phase = flaky
    agent = Agent(
        url="ws://localhost:8765",
        state=GameState(),
        role=role,
        prompts_dir=tmp_path,
        transport=transport,
        phase_engine=PhaseEngine(continuous_phases={"market"}, min_action_delay=0, max_action_delay=0),
    )

    with caplog.at_level(logging.ERROR):
        await agent.handle_phase_transition("market")
        for _ in range(20):
            await asyncio.sleep(0)
    await agent.stop()

    assert calls >= 3
    assert len(transport.sent) == calls - 1
    errors = [r for r in caplog.records if r.levelno == logging.ERROR and r.exc_info]
    assert errors and "provider outage" in str(errors[0].exc_info[1])


@pytest.mark.asyncio
async def test_repeated_turn_phase_transition_does_not_start_second_decision(role, tmp_path: Path):
    transport = FakeTransport()
    gate = asyncio.Event()
    calls = 0

    async def slow(phase, state, prompts_dir):
        nonlocal calls
        calls += 1
        await gate.wait()
        return {"meta": {"type": "choose"}, "payload": {}}

    role.handle_phase = slow
    agent = Agent(url="ws://localhost:8765", state=GameState(), role=role, prompts_dir=tmp_path, transport=transport)

    first = asyncio.create_task(agent.handle_phase_transition("decision"))
    await asyncio.sleep(0)
    await asyncio.wait_for(agent.handle_phase_transition("decision"), timeout=1)
    gate.set()
    await first

    assert calls == 1
    assert len(transport.sent) == 1


@pytest.mark.asyncio
async def test_stop_cancels_in_flight_decision(role, tmp_path: Path):
    transport = FakeTransport()
    gate = asyncio.Event()

    async def slow(phase, state, prompts_dir):
        await gate.wait()
        return {"meta": {"type": "choose"}, "payload": {}}

    role.handle_phase = slow
    agent = Agent(url="ws://localhost:8765", state=GameState(), role=role, prompts_dir=tmp_path, transport=transport)

    entry = asyncio.create_task(agent.handle_phase_transition("decision"))
    await asyncio.sleep(0)
    await agent.stop()
    gate.set()
    await entry

    assert transport.sent == []
