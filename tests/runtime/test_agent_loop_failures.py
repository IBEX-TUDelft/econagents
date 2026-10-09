"""IBEX-game_suite#7: an exception in the continuous phase loop must not end participation silently.

``Agent._continuous_phase_loop`` catches only ``CancelledError``. Any other exception raised by one
decision (a prompt render error, a transport failure, a parser bug) ends the loop task; the agent
then takes no further market actions for the rest of the phase, nothing is reported on any logger,
and ``Agent.start()`` (what ``GameRunner.spawn_agent`` awaits) keeps running as if all were well (at
best asyncio prints "Task exception was never retrieved" when the task is garbage-collected).

The issue allows the error to be "surfaced to the runner (recorded and/or re-raised)", so the tests
accept either design:
- participation: the loop keeps deciding, OR the exception reaches the runner (``Agent.start()``
  ends with it);
- reporting: an ERROR record carrying the exception on any logger (not asyncio's own
  "never retrieved" message), OR the exception reaches the runner.

The agent runs as in ``GameRunner``: ``Agent.start()`` in a task, over a fake transport that listens
until stopped. Gates instead of sleeps: action delays are zero and waits are bounded by 2 s.
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
FAILURE = "prompt render failed"


class FakeTransport:
    def __init__(self):
        self.sent: list[str] = []
        self._stopped = asyncio.Event()

    async def start_listening(self) -> None:
        await self._stopped.wait()

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def stop(self) -> None:
        self._stopped.set()


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
            raise RuntimeError(FAILURE)
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


def _carries_failure(exc: BaseException | None, seen: set[int] | None = None) -> bool:
    seen = seen if seen is not None else set()
    if exc is None or id(exc) in seen:
        return False
    seen.add(id(exc))
    if FAILURE in str(exc):
        return True
    nested = list(getattr(exc, "exceptions", ()) or ())
    return any(_carries_failure(e, seen) for e in [exc.__cause__, exc.__context__, *nested])


def surfaced_to_runner(run: asyncio.Task) -> bool:
    """``Agent.start()`` (the runner's await) ended with the loop's exception."""
    return run.done() and not run.cancelled() and _carries_failure(run.exception())


def reported(records: list[logging.LogRecord]) -> list[logging.LogRecord]:
    return [
        r
        for r in records
        if r.name != "asyncio"
        and r.levelno >= logging.ERROR
        and (FAILURE in r.getMessage() or (r.exc_info and _carries_failure(r.exc_info[1])))
    ]


async def _start(agent: Agent) -> asyncio.Task:
    run = asyncio.create_task(agent.start())
    await asyncio.sleep(0)
    await agent.handle_phase_transition("market")
    return run


async def _stop(agent: Agent, run: asyncio.Task) -> None:
    agent.in_continuous_phase = False
    task = agent._continuous_task
    if task is not None:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    await agent.transport.stop()
    await asyncio.gather(run, return_exceptions=True)


@pytest.mark.asyncio
async def test_failed_decision_does_not_silently_end_participation(tmp_path: Path):
    handler = FailingSecondDecision()
    agent = _agent(tmp_path, handler, logging.getLogger("gs7.loop.survives"))
    run = await _start(agent)
    try:
        await asyncio.wait_for(handler.failed.wait(), BOUND_S)
        acted = asyncio.create_task(handler.called_after_failure.wait())
        await asyncio.wait({acted, run}, timeout=BOUND_S, return_when=asyncio.FIRST_COMPLETED)
        acted.cancel()
        if not (handler.called_after_failure.is_set() or surfaced_to_runner(run)):
            pytest.fail(
                f"one decision raised RuntimeError and the market loop ended: no decision in the next {BOUND_S}s "
                f"and Agent.start() did not end with the error (handle_phase calls={handler.calls}, "
                f"loop task done={agent._continuous_task.done()}, Agent.start() done={run.done()})"
            )
    finally:
        await _stop(agent, run)


@pytest.mark.asyncio
async def test_failed_decision_is_reported_or_surfaced_to_the_runner(tmp_path: Path, caplog):
    handler = FailingSecondDecision()
    agent = _agent(tmp_path, handler, logging.getLogger("gs7.loop.reports"))
    with caplog.at_level(logging.DEBUG):
        run = await _start(agent)
        try:
            await asyncio.wait_for(handler.failed.wait(), BOUND_S)
            for _ in range(3):
                await asyncio.sleep(0)
            if not reported(caplog.records):
                await asyncio.wait({run}, timeout=BOUND_S)
            assert reported(caplog.records) or surfaced_to_runner(run), (
                f"the continuous loop's RuntimeError({FAILURE!r}) was neither logged at ERROR on any logger nor "
                f"raised to the runner (Agent.start() done={run.done()}); log: "
                f"{[(r.name, r.levelname, r.getMessage()) for r in caplog.records]}"
            )
        finally:
            await _stop(agent, run)
