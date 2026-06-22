import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from econagents.runtime import Agent
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
