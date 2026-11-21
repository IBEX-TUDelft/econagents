"""``GameRunner`` stops its timeout budgets while the game is paused (ibex 0.9.0)."""

import logging
from typing import Any

import pytest

from econagents.domain import Event
from econagents.runtime.game_clock import GameClock
from econagents.runtime.game_runner import GameRunner, GameRunnerConfig


class ReportingAgent:
    """The part of ``Agent`` the runner's clock reads: event handlers and ``paused``."""

    phase_transition_event = "snapshot"
    phase_identifier_key = "currentPhase"

    def __init__(self) -> None:
        self.paused = False
        self.handlers: dict[str, list[Any]] = {}

    def register_event_handler(self, event_type: str, handler: Any) -> "ReportingAgent":
        self.handlers.setdefault(event_type, []).append(handler)
        return self

    def receive(self, event_type: str, paused: bool) -> None:
        self.paused = paused
        for handler in self.handlers.get(event_type, []):
            handler(Event(type=event_type, data={"currentPhase": "market"}))


@pytest.mark.asyncio
async def test_agents_tell_the_clock_when_the_game_is_paused(tmp_path):
    agent = ReportingAgent()
    config = GameRunnerConfig(hostname="localhost", port=1234, path="ws", game_id=1, logs_dir=tmp_path)
    runner = GameRunner(config, [agent])  # type: ignore[list-item]
    runner._clock = GameClock(
        max_game_duration=10,
        max_pre_game_duration=None,
        pre_game_phases={"introduction"},
        logger=logging.getLogger("test_game_runner_pause"),
    )

    agent.receive("game-paused", True)
    assert runner._clock.paused
    agent.receive("game-resumed", False)
    assert not runner._clock.paused
    agent.receive("snapshot", True)
    assert runner._clock.paused, "an agent that joins during a pause reports it from its snapshot"
    agent.receive("snapshot", False)
    assert not runner._clock.paused


def test_pause_reports_before_the_run_starts_are_ignored(tmp_path):
    agent = ReportingAgent()
    config = GameRunnerConfig(hostname="localhost", port=1234, path="ws", game_id=1, logs_dir=tmp_path)
    GameRunner(config, [agent])  # type: ignore[list-item]

    agent.receive("game-paused", True)
