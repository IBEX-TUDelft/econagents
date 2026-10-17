"""Disposition, unknown-policy and decision-input options of ``Agent`` (IBEX-game_suite#22).

The lifecycle checks the reproduction harness runs live in ``test_agent_decision_lifecycle.py``;
these cover the remaining options: ``on_unknown="continue"``, the bounded reconciliation requests,
the revision guards, a tracker that does not wait or fails, and a submission whose send raised.
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
BID = {"meta": {"type": "post-order"}, "payload": {"type": "bid", "price": 10}}


class FakeTransport:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.fail: BaseException | None = None

    async def start_listening(self) -> None:
        pass

    async def send(self, message: str) -> None:
        if self.fail is not None:
            raise self.fail
        self.sent.append(message)

    async def stop(self) -> None:
        pass

    def orders(self) -> list[str]:
        return [m for m in self.sent if json.loads(m)["meta"]["type"] == "post-order"]


class Role:
    """Market decisions return ``result``; ``during`` runs inside each call (to change live state)."""

    name = "trader"
    prompt_renderer = object()
    response_parser = object()

    def __init__(self, result: dict | None = BID, during=None) -> None:
        self.result = result
        self.during = during
        self.calls = 0
        self.states: list[Any] = []

    async def handle_phase(self, phase, state, prompts_dir):
        if phase != MARKET:
            return None
        self.calls += 1
        self.states.append(state)
        if self.during is not None:
            self.during(self.calls)
        await asyncio.sleep(0)
        return self.result


class Tracker:
    """``ack`` resolves the oldest submission as accepted, ``drop`` as unknown; ``reconcile`` settles a dropped one."""

    def __init__(self, wait: bool = True, fail: bool = False) -> None:
        self.wait = wait
        self.fail = fail
        self.pending: list[str] = []
        self.untransmitted: list[str] = []
        self.dropped: list[str] = []

    def submitted(self, decision_id, message, state) -> bool:
        if self.fail:
            raise RuntimeError("tracker broke")
        self.pending.append(decision_id)
        return self.wait

    def observe(self, event, state):
        if event.type == "reconcile" and self.dropped:
            return [(self.dropped.pop(0), event.data.get("disposition", "accepted"))]
        if event.type in ("ack", "drop") and self.pending:
            decision_id = self.pending.pop(0)
            if event.type == "drop":
                self.dropped.append(decision_id)
            return [(decision_id, "accepted" if event.type == "ack" else "unknown")]
        return []

    def not_transmitted(self, decision_id) -> None:
        self.untransmitted.append(decision_id)
        self.pending.remove(decision_id)


def make_agent(role, tmp_path: Path, delay: int = 0, **options: Any) -> tuple[Agent, FakeTransport]:
    transport = FakeTransport()
    agent = Agent(
        url="ws://unused",
        state=GameState(),
        role=role,
        prompts_dir=tmp_path,
        transport=transport,
        phase_transition_event="snapshot",
        phase_identifier_key="currentPhase",
        phase_engine=PhaseEngine(continuous_phases={MARKET}, min_action_delay=delay, max_action_delay=delay),
        **options,
    )
    return agent, transport


def snapshot(phase: str = MARKET) -> Event:
    return Event(type="snapshot", data={"currentPhase": phase})


def players(number: int) -> Event:
    return Event(type="players-updated", data={"players": [{"playerNumber": number}]})


async def spin(n: int = 50) -> None:
    for _ in range(n):
        await asyncio.sleep(0)


async def shutdown(agent: Agent, *tasks: asyncio.Task) -> None:
    await agent.stop()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_continue_policy_records_unknown_without_blocking(tmp_path):
    records: list[dict] = []
    role = Role()
    tracker = Tracker()
    agent, transport = make_agent(
        role, tmp_path, disposition_tracker=tracker, decision_trace=records.append, on_unknown="continue"
    )
    entry = asyncio.create_task(agent.on_event(snapshot()))
    await spin()
    try:
        assert role.calls == 1
        await agent.on_event(Event(type="drop"))
        await spin()
        assert [r["disposition"] for r in records] == ["unknown"]
        assert role.calls == 2, "on_unknown='continue' must not hold the next decision"
    finally:
        await shutdown(agent, entry)


@pytest.mark.asyncio
async def test_continue_policy_traces_a_later_reconciliation(tmp_path):
    records: list[dict] = []
    role = Role()
    agent, _ = make_agent(
        role, tmp_path, delay=3600, disposition_tracker=Tracker(), decision_trace=records.append, on_unknown="continue"
    )
    entry = asyncio.create_task(agent.on_event(snapshot()))
    await spin()
    try:
        await agent.on_event(Event(type="drop"))
        await agent.on_event(Event(type="reconcile", data={"disposition": "filled"}))
        await agent.on_event(Event(type="reconcile", data={"disposition": "accepted"}))
        assert [(r["disposition"], r.get("reconciled_from")) for r in records] == [
            ("unknown", None),
            ("filled", "unknown"),
        ]
    finally:
        await shutdown(agent, entry)


@pytest.mark.asyncio
async def test_block_policy_requests_reconciliation_a_bounded_number_of_times(tmp_path):
    requests: list[int] = []
    role = Role()
    agent, _ = make_agent(
        role,
        tmp_path,
        disposition_tracker=Tracker(),
        reconcile_request=lambda: requests.append(1),
        reconcile_retry_interval=0.01,
        reconcile_retry_limit=3,
    )
    entry = asyncio.create_task(agent.on_event(snapshot()))
    await spin()
    try:
        await agent.on_event(Event(type="drop"))
        await asyncio.sleep(0.15)
        assert len(requests) == 3, f"{len(requests)} reconciliation requests, want the limit of 3"
        assert role.calls == 1
        await agent.on_event(Event(type="reconcile"))
        await spin()
        assert role.calls == 2, "the reconciliation must release the next decision"
    finally:
        await shutdown(agent, entry)


@pytest.mark.asyncio
async def test_frozen_input_sends_and_records_that_the_state_changed(tmp_path):
    records: list[dict] = []
    agent: Agent | None = None

    def change(_call: int) -> None:
        agent.state.meta.players = [{"playerNumber": 9}]

    role = Role(during=change)
    agent, transport = make_agent(role, tmp_path, delay=3600, decision_trace=records.append)
    entry = asyncio.create_task(agent.on_event(snapshot()))
    await spin()
    try:
        assert role.states[0] is not agent.state
        assert role.states[0].meta.players == []
        assert len(transport.orders()) == 1
        [record] = records
        assert record["input_changed_during_call"] is True
        assert record["input_revision"] != record["send_revision"]
        assert (record["status"], record["disposition"]) == ("sent", "sent")
    finally:
        await shutdown(agent, entry)


@pytest.mark.asyncio
async def test_guard_discard_drops_an_action_decided_on_a_changed_state(tmp_path):
    records: list[dict] = []
    outcomes = []
    agent: Agent | None = None

    def change(call: int) -> None:
        agent.state.meta.players = [{"playerNumber": call}]

    role = Role(during=change)
    agent, transport = make_agent(
        role, tmp_path, delay=3600, decision_trace=records.append, decision_input="guard-discard"
    )
    agent.register_action_listener(outcomes.append)
    entry = asyncio.create_task(agent.on_event(snapshot()))
    await spin()
    try:
        assert transport.sent == []
        assert [o.status for o in outcomes] == ["superseded"]
        assert records[0]["disposition"] == "superseded"
        assert role.states[0] is agent.state, "guard modes decide on the live state"
    finally:
        await shutdown(agent, entry)


@pytest.mark.asyncio
async def test_guard_rerun_decides_again_once_and_sends_when_the_state_held(tmp_path):
    agent: Agent | None = None

    def change(call: int) -> None:
        if call == 1:
            agent.state.meta.players = [{"playerNumber": 1}]

    role = Role(during=change)
    agent, transport = make_agent(role, tmp_path, delay=3600, decision_input="guard-rerun")
    entry = asyncio.create_task(agent.on_event(snapshot()))
    await spin()
    try:
        assert role.calls == 2
        assert len(transport.orders()) == 1
    finally:
        await shutdown(agent, entry)


@pytest.mark.asyncio
async def test_guard_rerun_discards_when_the_state_changes_again(tmp_path):
    agent: Agent | None = None

    def change(call: int) -> None:
        agent.state.meta.players = [{"playerNumber": call}]

    role = Role(during=change)
    agent, transport = make_agent(role, tmp_path, delay=3600, decision_input="guard-rerun")
    entry = asyncio.create_task(agent.on_event(snapshot()))
    await spin()
    try:
        assert role.calls == 2
        assert transport.sent == []
    finally:
        await shutdown(agent, entry)


@pytest.mark.asyncio
async def test_tracker_that_does_not_wait_settles_on_send(tmp_path):
    records: list[dict] = []
    role = Role()
    agent, transport = make_agent(
        role, tmp_path, disposition_tracker=Tracker(wait=False), decision_trace=records.append
    )
    entry = asyncio.create_task(agent.on_event(snapshot()))
    await spin()
    try:
        assert role.calls >= 2
        assert records[0]["disposition"] == "sent"
    finally:
        await shutdown(agent, entry)


@pytest.mark.asyncio
async def test_failing_tracker_is_logged_and_does_not_hold_decisions(tmp_path, caplog):
    role = Role()
    agent, transport = make_agent(role, tmp_path, disposition_tracker=Tracker(fail=True))
    entry = asyncio.create_task(agent.on_event(snapshot()))
    await spin()
    try:
        assert role.calls >= 2
        assert "Disposition tracker failed" in caplog.text
    finally:
        await shutdown(agent, entry)


@pytest.mark.asyncio
async def test_untransmitted_submission_is_withdrawn_from_the_tracker(tmp_path):
    records: list[dict] = []
    role = Role()
    tracker = Tracker()
    agent, transport = make_agent(role, tmp_path, disposition_tracker=tracker, decision_trace=records.append)
    transport.fail = ConnectionError("socket closed")
    entry = asyncio.create_task(agent.on_event(snapshot()))
    await spin()
    try:
        assert len(tracker.untransmitted) >= 2, "an untransmitted submission must not hold the next decision"
        assert tracker.pending == []
        assert records[0]["disposition"] == "not-transmitted"
    finally:
        await shutdown(agent, entry)


@pytest.mark.asyncio
async def test_pending_disposition_holds_the_next_phase_until_resolved(tmp_path):
    role = Role()
    tracker = Tracker()
    agent, transport = make_agent(role, tmp_path, delay=3600, disposition_tracker=tracker)
    entry = asyncio.create_task(agent.on_event(snapshot()))
    await spin()
    reentry = asyncio.create_task(agent.on_event(snapshot("other")))
    await spin()
    market = asyncio.create_task(agent.on_event(snapshot()))
    await spin()
    try:
        assert role.calls == 1, "a decision started while the earlier submission had no disposition"
        await agent.on_event(Event(type="ack"))
        await spin()
        assert role.calls == 2
    finally:
        await shutdown(agent, entry, reentry, market)


def test_invalid_options_are_refused(tmp_path):
    with pytest.raises(ValueError):
        make_agent(Role(), tmp_path, on_unknown="ignore")
    with pytest.raises(ValueError):
        make_agent(Role(), tmp_path, decision_input="live")
    with pytest.raises(ValueError):
        make_agent(Role(), tmp_path, disposition_timeout=0)


@pytest.mark.asyncio
async def test_frozen_copy_does_not_share_nested_state(tmp_path):
    role = Role(result=None)
    agent, _ = make_agent(role, tmp_path, delay=3600)
    agent.state.meta.players = [{"playerNumber": 1}]
    entry = asyncio.create_task(agent.on_event(snapshot()))
    await spin()
    try:
        await agent.on_event(players(2))
        assert role.states[0].meta.players == [{"playerNumber": 1}]
    finally:
        await shutdown(agent, entry)
