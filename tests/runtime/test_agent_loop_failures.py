"""IBEX-game_suite#7: an exception in the continuous phase loop must not end participation silently.

``Agent._continuous_phase_loop`` catches only ``CancelledError``. Any other exception raised by one
decision (a prompt render error, a transport failure, a parser bug) ends the loop task; the agent
then takes no further market actions for the rest of the phase and nothing is reported on the
agent's logger (at best asyncio prints "Task exception was never retrieved" when the task is
garbage-collected).

Gates instead of sleeps: action delays are zero and the tests wait on asyncio.Events with a 2 s bound.
"""

import asyncio
import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from econagents.domain.role import Role
from econagents.domain.state.game import GameState
from econagents.runtime import Agent, PhaseEngine

BOUND_S = 2.0
ENVELOPE = {"meta": {"type": "post-order"}, "payload": {"price": 1}}


class FakeTransport:
    def __init__(self):
        self.sent: list[str] = []

    async def start_listening(self) -> None:
        return None

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def stop(self) -> None:
        return None


class FailingSecondDecision:
    """handle_phase: the phase-entry decision succeeds, the first loop decision raises, later ones succeed."""

    def __init__(self):
        self.calls = 0
        self.failed = asyncio.Event()
        self.called_after_failure = asyncio.Event()

    async def __call__(self, phase, state, prompts_path):
        self.calls += 1
        if self.calls == 2:
            self.failed.set()
            raise RuntimeError("prompt render failed")
        if self.calls > 2:
            self.called_after_failure.set()
        return ENVELOPE


def _agent(tmp_path: Path, handler, logger: logging.Logger) -> Agent:
    role = MagicMock(spec=Role)
    role.name = "trader"
    role.handle_phase = handler
    return Agent(
        url="ws://127.0.0.1:9",
        state=GameState(),
        role=role,
        prompts_dir=tmp_path,
        transport=FakeTransport(),
        phase_engine=PhaseEngine(continuous_phases={"market"}, min_action_delay=0, max_action_delay=0),
        logger=logger,
    )


async def _stop(agent: Agent) -> None:
    agent.in_continuous_phase = False
    task = agent._continuous_task
    if task is not None:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_continuous_loop_keeps_acting_after_a_failed_decision(tmp_path: Path):
    handler = FailingSecondDecision()
    agent = _agent(tmp_path, handler, logging.getLogger("gs7.loop.survives"))
    try:
        await agent.handle_phase_transition("market")
        await asyncio.wait_for(handler.failed.wait(), BOUND_S)
        try:
            await asyncio.wait_for(handler.called_after_failure.wait(), BOUND_S)
        except asyncio.TimeoutError:
            pytest.fail(
                f"one decision raised RuntimeError and the market loop ended: no decision in the next {BOUND_S}s "
                f"(handle_phase calls={handler.calls}, loop task done={agent._continuous_task.done()})"
            )
    finally:
        await _stop(agent)


@pytest.mark.asyncio
async def test_continuous_loop_failure_is_reported_on_the_agent_logger(tmp_path: Path, caplog):
    handler = FailingSecondDecision()
    name = "gs7.loop.reports"
    agent = _agent(tmp_path, handler, logging.getLogger(name))
    try:
        with caplog.at_level(logging.DEBUG, logger=name):
            await agent.handle_phase_transition("market")
            await asyncio.wait_for(handler.failed.wait(), BOUND_S)
            for _ in range(3):
                await asyncio.sleep(0)
        reported = [
            r
            for r in caplog.records
            if r.name == name
            and r.levelno >= logging.ERROR
            and (
                "prompt render failed" in r.getMessage()
                or (r.exc_info and "prompt render failed" in str(r.exc_info[1]))
            )
        ]
        assert reported, (
            "the continuous loop's RuntimeError('prompt render failed') was not reported on the agent logger; "
            f"agent log: {[(r.levelname, r.getMessage()) for r in caplog.records if r.name == name]}"
        )
    finally:
        await _stop(agent)
