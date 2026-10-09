"""Per-agent decision lifecycle (IBEX-game_suite#6, FPM-27).

The role is a stub whose decisions block on an ``asyncio.Event`` (a controllable slow model), so
every test is deterministic and makes no model or network call. The wiring matches the futarchy
runner: ``snapshot`` events drive phase transitions via ``currentPhase``, and ``market`` is the
continuous phase.

Test groups:

* behavioral: bugs observable through the current public API.
* interface proposal: generic disposition hooks that do not exist yet. The proposed shape is
  ``Agent(disposition_tracker=..., disposition_timeout=..., decision_trace=...)`` where the tracker
  has ``submitted(decision_id, message, state) -> bool`` (True: wait for a disposition) and
  ``observe(event, state) -> list[(decision_id, disposition)]``.
* decision-gated: behavior that depends on an open researcher/server decision.
* guard: behavior that already works and that a fix must keep.

Proposal and decision-gated tests are strict xfails so the suite stays green until they are
implemented; the reproduction harness runs them with ``--runxfail``.
"""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from econagents.domain import Event
from econagents.domain.state.game import GameState
from econagents.runtime import Agent, PhaseEngine

MARKET = "market"
NEXT_PHASE = "declaration_final"
BID = {
    "meta": {"type": "post-order", "component": {"type": "standard:dam", "name": "project"}},
    "payload": {"sender": 2, "type": "bid", "price": 6421.5, "timestamp": 0, "now": False},
}
TICKS = 50
PROPOSAL = pytest.mark.xfail(
    strict=True,
    reason="interface proposal (IBEX-game_suite#6): the Agent disposition hooks are not implemented yet",
)
GATED = pytest.mark.xfail(
    strict=True,
    reason="decision-gated (IBEX-game_suite#6): waits on an open researcher/server decision",
)


class FakeTransport:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def start_listening(self) -> None:
        pass

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def stop(self) -> None:
        pass

    def sent_types(self) -> list[str]:
        return [json.loads(m).get("meta", {}).get("type") for m in self.sent]

    def post_orders(self) -> list[str]:
        return [m for m in self.sent if json.loads(m).get("meta", {}).get("type") == "post-order"]


class GatedRole:
    """Stub role: market decisions wait on ``gate``; other phases return no action."""

    name = "developer"
    prompt_renderer = object()
    response_parser = object()

    def __init__(self, *, gated: bool, result: dict | None = BID) -> None:
        self.gate = asyncio.Event()
        if not gated:
            self.gate.set()
        self.result = result
        self.calls = 0
        self.active = 0
        self.max_active = 0
        self.inputs: list[tuple[Any, Any]] = []

    async def handle_phase(self, phase, state, prompts_dir):
        if phase != MARKET:
            return None
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        players_at_start = json.dumps(state.meta.players)
        try:
            await asyncio.sleep(0)
            await self.gate.wait()
        finally:
            self.active -= 1
        self.inputs.append((players_at_start, json.dumps(state.meta.players)))
        return self.result


class RecordingPhaseEngine(PhaseEngine):
    """PhaseEngine that remembers which task asked for each continuous-phase delay."""

    def __init__(self, delay: int) -> None:
        super().__init__(continuous_phases={MARKET}, min_action_delay=delay, max_action_delay=delay)
        self.scheduling_tasks: list[asyncio.Task] = []

    def next_action_delay(self) -> int:
        task = asyncio.current_task()
        if task is not None:
            self.scheduling_tasks.append(task)
        return super().next_action_delay()

    def live_schedulers(self) -> int:
        return len({t for t in self.scheduling_tasks if not t.done()})


class AckTracker:
    """Duck-typed disposition tracker for the proposed hook: ``ack``/``nack`` events resolve FIFO."""

    def __init__(self) -> None:
        self.pending: list[str] = []
        self.submissions: list[tuple[str, Any]] = []

    def submitted(self, decision_id: str, message: Any, state: Any) -> bool:
        self.pending.append(decision_id)
        self.submissions.append((decision_id, message))
        return True

    def observe(self, event: Event, state: Any) -> list[tuple[str, str]]:
        if event.type in ("ack", "nack") and self.pending:
            return [(self.pending.pop(0), "accepted" if event.type == "ack" else "refused")]
        return []


def make_agent(role, tmp_path: Path, delay: int = 3600, **proposal: Any) -> tuple[Agent, FakeTransport]:
    transport = FakeTransport()
    engine = proposal.pop("phase_engine", None) or PhaseEngine(
        continuous_phases={MARKET}, min_action_delay=delay, max_action_delay=delay
    )
    error = None
    try:
        agent = Agent(
            url="ws://unused",
            state=GameState(),
            role=role,
            prompts_dir=tmp_path,
            transport=transport,
            phase_transition_event="snapshot",
            phase_identifier_key="currentPhase",
            phase_engine=engine,
            **proposal,
        )
    except TypeError as exc:
        error = str(exc)
    if error is not None:
        pytest.fail(f"interface proposal not implemented: Agent({'=..., '.join(sorted(proposal))}=...) -> {error}")
    return agent, transport


def snapshot(phase: str) -> Event:
    return Event(type="snapshot", data={"currentPhase": phase})


async def spin(n: int = TICKS) -> None:
    for _ in range(n):
        await asyncio.sleep(0)


async def shutdown(agent: Agent, *tasks: asyncio.Task) -> None:
    await agent.stop()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await spin(5)


async def wait_for(predicate, timeout: float = 5.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return predicate()


# ---------------------------------------------------------------------------
# Behavioral bug checks (current public API)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_phase_entry_and_continuous_loop_never_run_concurrent_decisions(tmp_path):
    """Game 16 path: the phase-entry decision and the loop's first iteration overlap."""
    role = GatedRole(gated=True)
    agent, _ = make_agent(role, tmp_path, delay=0)
    entry = asyncio.create_task(agent.on_event(snapshot(MARKET)))
    await spin()
    try:
        assert role.max_active == 1, (
            f"{role.max_active} concurrent market decisions for one agent after one market phase entry"
        )
    finally:
        role.gate.set()
        await shutdown(agent, entry)


@pytest.mark.asyncio
async def test_same_phase_snapshot_does_not_start_second_decision_while_one_is_in_flight(tmp_path):
    """A second snapshot for the current phase (get-snapshot reply, reconnect) is not a new decision slot."""
    role = GatedRole(gated=True)
    agent, _ = make_agent(role, tmp_path, delay=3600)
    first = asyncio.create_task(agent.on_event(snapshot(MARKET)))
    await spin()
    second = asyncio.create_task(agent.on_event(snapshot(MARKET)))
    await spin()
    try:
        assert role.max_active == 1, (
            f"{role.max_active} concurrent market decisions after a repeated same-phase snapshot"
        )
    finally:
        role.gate.set()
        await shutdown(agent, first, second)


@pytest.mark.asyncio
async def test_same_phase_snapshot_leaves_one_continuous_loop(tmp_path):
    """Two same-phase snapshots must leave exactly one live continuous-phase scheduler."""
    role = GatedRole(gated=False, result=None)
    engine = RecordingPhaseEngine(delay=3600)
    agent, _ = make_agent(role, tmp_path, phase_engine=engine)
    first = asyncio.create_task(agent.on_event(snapshot(MARKET)))
    await spin()
    second = asyncio.create_task(agent.on_event(snapshot(MARKET)))
    await spin()
    try:
        assert engine.live_schedulers() == 1, (
            f"{engine.live_schedulers()} continuous-phase loops alive for one agent after two same-phase snapshots"
        )
    finally:
        await shutdown(agent, first, second, *engine.scheduling_tasks)


@pytest.mark.asyncio
async def test_stale_market_result_is_not_submitted_after_phase_change(tmp_path):
    """A decision taken in `market` must not reach the server after the move to the next phase."""
    role = GatedRole(gated=True)
    agent, transport = make_agent(role, tmp_path, delay=3600)
    entry = asyncio.create_task(agent.on_event(snapshot(MARKET)))
    await spin()
    assert role.active == 1
    await agent.on_event(snapshot(NEXT_PHASE))
    role.gate.set()
    await spin()
    try:
        assert "post-order" not in transport.sent_types(), (
            f"stale market action submitted into {NEXT_PHASE}: {transport.sent_types()}"
        )
    finally:
        await shutdown(agent, entry)


@pytest.mark.asyncio
async def test_stale_market_result_is_not_submitted_when_market_returns(tmp_path):
    """market -> next phase -> market: the first market's result is stale even though the phase id matches."""
    role = GatedRole(gated=True)
    agent, transport = make_agent(role, tmp_path, delay=3600)
    entry = asyncio.create_task(agent.on_event(snapshot(MARKET)))
    await spin()
    first_gate = role.gate
    await agent.on_event(snapshot(NEXT_PHASE))
    role.gate = asyncio.Event()
    reentry = asyncio.create_task(agent.on_event(snapshot(MARKET)))
    await spin()
    first_gate.set()
    await spin()
    try:
        assert transport.post_orders() == [], f"first market epoch's result submitted after re-entry: {transport.sent}"
        role.gate.set()
        await spin()
        assert len(transport.post_orders()) == 1, f"new market epoch's decision not submitted: {transport.sent}"
    finally:
        role.gate.set()
        await shutdown(agent, entry, reentry)


# ---------------------------------------------------------------------------
# Interface-proposal checks (disposition hook, trace, timeout)
# ---------------------------------------------------------------------------


@PROPOSAL
@pytest.mark.asyncio
async def test_proposal_next_decision_waits_for_disposition(tmp_path):
    """No second decision/submission until the previous submission has a disposition; then exactly one more."""
    role = GatedRole(gated=False)
    tracker = AckTracker()
    agent, transport = make_agent(role, tmp_path, delay=0, disposition_tracker=tracker)
    entry = asyncio.create_task(agent.on_event(snapshot(MARKET)))
    await spin()
    try:
        assert (role.calls, len(transport.post_orders())) == (1, 1), (
            f"{role.calls} decisions / {len(transport.post_orders())} post-orders in {TICKS} ticks "
            "without any disposition for the first submission"
        )
        await agent.on_event(Event(type="ack"))
        await spin()
        assert (role.calls, len(transport.post_orders())) == (2, 2), (
            f"after one disposition: {role.calls} decisions / {len(transport.post_orders())} post-orders (want 2/2)"
        )
        first, second = transport.post_orders()
        assert first == second, "the later independent decision must be allowed to send byte-identical payload"
        ids = [decision_id for decision_id, _ in tracker.submissions]
        assert len(set(ids)) == len(ids) == 2, f"identical submissions must carry distinct decision ids: {ids}"
    finally:
        await shutdown(agent, entry)


@PROPOSAL
@pytest.mark.asyncio
async def test_proposal_trace_links_decision_to_input_submission_and_disposition(tmp_path):
    """One trace record per decision: id, phase, epoch, input revision, submission bytes, disposition."""
    records: list[dict] = []
    role = GatedRole(gated=False)
    tracker = AckTracker()
    agent, transport = make_agent(
        role, tmp_path, delay=3600, disposition_tracker=tracker, decision_trace=records.append
    )
    entry = asyncio.create_task(agent.on_event(snapshot(MARKET)))
    await spin()
    await agent.on_event(Event(type="ack"))
    await spin()
    try:
        assert len(records) == 1, f"expected 1 decision record after one accepted submission, got {records}"
        record = records[0]
        missing = {"decision_id", "phase", "phase_epoch", "submitted", "disposition"} - set(record)
        assert not missing, f"decision record lacks {sorted(missing)}: {record}"
        assert {"input_revision", "input_state_hash"} & set(record), f"decision record has no input revision: {record}"
        assert record["phase"] == MARKET
        assert record["submitted"] == transport.post_orders()[0]
        assert record["disposition"] == "accepted"
    finally:
        await shutdown(agent, entry)


@PROPOSAL
@pytest.mark.asyncio
async def test_proposal_stale_phase_result_is_recorded_not_sent(tmp_path):
    """The discarded stale result is kept in the trace with disposition 'stale-phase'."""
    records: list[dict] = []
    role = GatedRole(gated=True)
    agent, transport = make_agent(
        role, tmp_path, delay=3600, disposition_tracker=AckTracker(), decision_trace=records.append
    )
    entry = asyncio.create_task(agent.on_event(snapshot(MARKET)))
    await spin()
    await agent.on_event(snapshot(NEXT_PHASE))
    role.gate.set()
    await spin()
    try:
        stale = [r for r in records if r.get("disposition") == "stale-phase"]
        assert len(stale) == 1, f"expected one 'stale-phase' decision record, got {records}"
        assert stale[0].get("phase") == MARKET and not stale[0].get("submitted"), stale[0]
        assert "post-order" not in transport.sent_types()
    finally:
        await shutdown(agent, entry)


@PROPOSAL
@pytest.mark.asyncio
async def test_proposal_missing_disposition_times_out_as_unknown(tmp_path):
    """A silent server drop ends in the configured timeout as 'unknown', never as accepted."""
    records: list[dict] = []
    role = GatedRole(gated=False)
    agent, transport = make_agent(
        role,
        tmp_path,
        delay=0,
        disposition_tracker=AckTracker(),
        disposition_timeout=0.05,
        decision_trace=records.append,
    )
    entry = asyncio.create_task(agent.on_event(snapshot(MARKET)))
    try:
        resolved = await wait_for(lambda: bool(records))
        assert resolved, f"no decision record {5.0}s after a 0.05s disposition timeout ({role.calls} decisions)"
        disposition = str(records[0].get("disposition"))
        assert disposition.startswith("unknown"), f"silent drop recorded as {disposition!r}, want 'unknown...'"
    finally:
        await shutdown(agent, entry)


# ---------------------------------------------------------------------------
# Decision-gated checks (open researcher/server questions; see the repro spec)
# ---------------------------------------------------------------------------


@GATED
@pytest.mark.asyncio
async def test_gated_unknown_disposition_blocks_until_snapshot_reconciles(tmp_path):
    """Option under discussion: after an 'unknown' disposition, wait for a reconciling snapshot."""
    records: list[dict] = []
    role = GatedRole(gated=False)
    agent, _ = make_agent(
        role,
        tmp_path,
        delay=0,
        disposition_tracker=AckTracker(),
        disposition_timeout=0.05,
        decision_trace=records.append,
    )
    entry = asyncio.create_task(agent.on_event(snapshot(MARKET)))
    try:
        assert await wait_for(lambda: bool(records)), "no decision record after the disposition timeout"
        await asyncio.sleep(0.2)
        assert role.calls == 1, f"{role.calls} decisions after an unknown disposition and no reconciling snapshot"
        await agent.on_event(snapshot(MARKET))
        assert await wait_for(lambda: role.calls >= 2), "no decision after the reconciling snapshot"
    finally:
        await shutdown(agent, entry)


@GATED
@pytest.mark.asyncio
async def test_gated_decision_input_is_frozen_while_in_flight(tmp_path):
    """Option under discussion: the role sees a frozen input copy, not live state mutated mid-decision."""
    role = GatedRole(gated=True)
    agent, _ = make_agent(role, tmp_path, delay=3600)
    entry = asyncio.create_task(agent.on_event(snapshot(MARKET)))
    await spin()
    await agent.on_event(Event(type="players-updated", data={"players": [{"playerNumber": 9}]}))
    assert agent.state.meta.players == [{"playerNumber": 9}]
    role.gate.set()
    await spin()
    try:
        at_start, at_end = role.inputs[0]
        assert at_start == at_end, f"decision input changed while the model call was in flight: {at_start} -> {at_end}"
    finally:
        await shutdown(agent, entry)


# ---------------------------------------------------------------------------
# Guards (pass before and after the fix)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_guard_hold_results_do_not_block_continuous_phase(tmp_path):
    """A decision that sends nothing (hold/no-op) is resolved at once; the loop keeps deciding."""
    role = GatedRole(gated=False, result=None)
    agent, transport = make_agent(role, tmp_path, delay=0)
    entry = asyncio.create_task(agent.on_event(snapshot(MARKET)))
    await spin()
    try:
        assert role.calls >= 2, f"only {role.calls} decision(s) in {TICKS} ticks although nothing awaited a disposition"
        assert transport.sent == []
    finally:
        await shutdown(agent, entry)


@pytest.mark.asyncio
async def test_guard_identical_payloads_allowed_without_disposition_tracker(tmp_path):
    """Without a tracker a submission is resolved on send: repeated identical orders still go out."""
    role = GatedRole(gated=False)
    agent, transport = make_agent(role, tmp_path, delay=0)
    entry = asyncio.create_task(agent.on_event(snapshot(MARKET)))
    await spin()
    try:
        orders = transport.post_orders()
        assert len(orders) >= 2 and len(set(orders)) == 1, f"identical later submissions were suppressed: {orders}"
    finally:
        await shutdown(agent, entry)


@pytest.mark.asyncio
async def test_guard_same_phase_snapshot_keeps_in_flight_result(tmp_path):
    """A same-phase snapshot is not a phase change: the in-flight market result is still submitted."""
    role = GatedRole(gated=True)
    agent, transport = make_agent(role, tmp_path, delay=3600)
    first = asyncio.create_task(agent.on_event(snapshot(MARKET)))
    await spin()
    second = asyncio.create_task(agent.on_event(snapshot(MARKET)))
    await spin()
    role.gate.set()
    await spin()
    try:
        assert len(transport.post_orders()) >= 1, (
            f"in-flight market result dropped on a same-phase snapshot: {transport.sent}"
        )
    finally:
        await shutdown(agent, first, second)
