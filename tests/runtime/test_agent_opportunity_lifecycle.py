"""Decision-lifecycle invariants that Family B opportunity consumption relies on (IBEX-game_suite#12).

Family B allows one unresolved actor opportunity at a time: a duplicate snapshot or phase event
must never start a second decision while one is in flight. The per-agent invariant is shared
with IBEX-game_suite#6; the opportunity contract itself is tested in futarchy-agents.
"""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from econagents.domain import Event
from econagents.domain.role import Role
from econagents.domain.state.game import GameState
from econagents.runtime import Agent, PhaseEngine

MARKET = "market"
DECLARATION = "declaration"


class FakeTransport:
    def __init__(self):
        self.sent: list[str] = []

    async def start_listening(self) -> None:
        pass

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def stop(self) -> None:
        pass


class GatedPolicy:
    """Role.handle_phase stand-in that blocks every decision on a gate and tracks concurrency."""

    def __init__(self) -> None:
        self.gate = asyncio.Event()
        self.in_flight = 0
        self.peak = 0
        self.calls: list[str] = []

    async def __call__(self, phase, state, prompts_path):
        self.calls.append(phase)
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        try:
            await self.gate.wait()
        finally:
            self.in_flight -= 1
        return None


def make_agent(policy, tmp_path: Path) -> Agent:
    role = MagicMock(spec=Role)
    role.name = "test_role"
    role.handle_phase = policy
    return Agent(
        url="ws://localhost:8765",
        state=GameState(),
        role=role,
        prompts_dir=tmp_path,
        transport=FakeTransport(),
        phase_transition_event="snapshot",
        phase_identifier_key="currentPhase",
        phase_engine=PhaseEngine(continuous_phases={MARKET}, min_action_delay=0, max_action_delay=0),
    )


def deliver(agent: Agent, phase: str) -> asyncio.Task:
    """Dispatch a phase snapshot the way Agent._raw_message_received does (one task per message)."""
    return asyncio.create_task(agent.on_event(Event(type="snapshot", data={"currentPhase": phase})))


async def settle(turns: int = 50) -> None:
    for _ in range(turns):
        await asyncio.sleep(0)


async def eventually(predicate, timeout: float) -> bool:
    """Poll in real time, so a decision started after a debounce or an awaited delay is still seen."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() >= deadline:
            return False
        await asyncio.sleep(0.01)
    return True


OVERLAP_WINDOW = 0.3


async def shutdown(agent: Agent, policy: GatedPolicy, tasks: list[asyncio.Task]) -> None:
    await agent.stop()
    policy.gate.set()
    await asyncio.gather(*tasks, return_exceptions=True)
    await settle()


@pytest.mark.asyncio
async def test_single_continuous_phase_snapshot_entry_action_and_loop_do_not_overlap(tmp_path: Path):
    """Behavioral: ONE market snapshot already starts two decisions.

    Agent.handle_phase_transition creates the continuous loop task and then awaits the entry action;
    the loop's first iteration decides while the entry decision is still pending.
    """
    policy = GatedPolicy()
    agent = make_agent(policy, tmp_path)

    tasks = [deliver(agent, MARKET)]
    started = await eventually(lambda: len(policy.calls) >= 1, timeout=5)
    await eventually(lambda: policy.peak > 1, timeout=OVERLAP_WINDOW)
    peak, calls = policy.peak, len(policy.calls)
    await shutdown(agent, policy, tasks)

    assert started, "the market snapshot started no decision at all"
    assert peak <= 1, (
        f"a single '{MARKET}' snapshot put {peak} decisions in flight for one actor ({calls} policy invocations): "
        "handle_phase_transition awaits the entry action while the continuous loop it just created also decides; "
        "Family B allows one unresolved opportunity"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "phase",
    [DECLARATION, MARKET],
    ids=["single-action-phase", "continuous-phase-needs-entry-vs-loop-fix-too"],
)
async def test_duplicate_same_phase_snapshot_starts_no_second_decision(phase, tmp_path: Path):
    """Behavioral: the phase snapshot plus the get-snapshot reply on join must give one decision in flight.

    The single-action case isolates the re-entry defect (a same-phase snapshot re-runs
    handle_phase_transition). The continuous case also overlaps the entry action with the loop
    (see the single-snapshot test), so it passes only once both defects are fixed.
    """
    policy = GatedPolicy()
    agent = make_agent(policy, tmp_path)

    tasks = [deliver(agent, phase)]
    started = await eventually(lambda: len(policy.calls) >= 1, timeout=5)
    tasks.append(deliver(agent, phase))
    await eventually(lambda: policy.peak > 1, timeout=OVERLAP_WINDOW)
    peak, calls = policy.peak, len(policy.calls)
    await shutdown(agent, policy, tasks)

    assert started, f"the first '{phase}' snapshot started no decision at all"
    assert peak <= 1, (
        f"{peak} decisions were in flight at once for one actor after two '{phase}' snapshots "
        f"({calls} policy invocations); a same-phase snapshot re-ran handle_phase_transition"
        + (" (and the entry action overlaps the continuous loop)" if phase == MARKET else "")
        + "; Family B allows one unresolved opportunity"
    )


@pytest.mark.asyncio
async def test_guard_continuous_phase_keeps_acting_after_each_decision_resolves(tmp_path: Path):
    """Guard: single-flight must not turn the continuous market into a single action."""
    third_call = asyncio.Event()
    calls: list[str] = []

    async def policy(phase, state, prompts_path):
        calls.append(phase)
        if len(calls) >= 3:
            third_call.set()
        return None

    agent = make_agent(policy, tmp_path)
    task = deliver(agent, MARKET)
    await asyncio.wait_for(third_call.wait(), timeout=10)
    await agent.stop()
    await asyncio.gather(task, return_exceptions=True)

    assert calls[:3] == [MARKET, MARKET, MARKET]


@pytest.mark.asyncio
async def test_guard_phase_change_during_pending_decision_runs_next_phase_once(tmp_path: Path):
    """Guard: suppressing duplicate snapshots must not swallow a real phase transition."""
    policy = GatedPolicy()
    agent = make_agent(policy, tmp_path)

    tasks = [deliver(agent, MARKET)]
    await eventually(lambda: len(policy.calls) >= 1, timeout=5)
    await settle()
    market_calls_before_change = policy.calls.count(MARKET)
    tasks.append(deliver(agent, DECLARATION))
    await settle()
    policy.gate.set()
    await eventually(lambda: DECLARATION in policy.calls, timeout=5)
    await asyncio.sleep(OVERLAP_WINDOW)
    calls = list(policy.calls)
    await shutdown(agent, policy, tasks)

    assert market_calls_before_change >= 1
    assert calls.count(DECLARATION) == 1, f"next phase decisions: {calls}"
    assert calls.count(MARKET) == market_calls_before_change, f"market kept deciding after the phase changed: {calls}"
