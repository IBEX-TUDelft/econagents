"""Decision gate for non-continuous phase occurrences (IBEX-game_suite#8, WP-E2a).

With re-authentication every reconnect ends in a snapshot of the phase the agent is already in
(futarchy-agents requests one on its own ``player-joined``). Once the decision for that phase
occurrence has completed, the snapshot must not start another one: on futharcy-agents a second
declaration is refused and a second speculation silently replaces the first.

Test groups:

* gate: a completed decision is not taken again for the same occurrence (fails before the gate).
* guard: what must still be decided again (passes before and after the gate).
* hook: the optional ``Agent(decision_gate=...)`` store (fails before the gate: no such argument).

The wiring matches the futarchy runner: ``snapshot`` events drive transitions via ``currentPhase``,
the round comes from ``currentRound``, and ``market`` is the continuous phase. No name added by the
gate is imported at module level, so the guards also run against an econagents without it.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import pytest
from pydantic import Field

from econagents.domain import Event
from econagents.domain.state.fields import EventField
from econagents.domain.state.game import GameState, MetaInformation
from econagents.runtime import Agent, PhaseEngine

DECLARATION = "declaration_first"
SPECULATION = "speculation_first"
MARKET = "market"
GATE_LOG = "its decision already completed"


class RoundMeta(MetaInformation):
    round: int = EventField(default=0, event_key="currentRound")


class RoundGameState(GameState):
    meta: RoundMeta = Field(default_factory=RoundMeta)


def declaration(value: int) -> dict[str, Any]:
    return {
        "meta": {"type": "submit-declaration", "component": {"type": "standard:declaration"}},
        "payload": {"values": [{"condition": "project", "value": value}]},
    }


def snapshot(phase: str, round_: int = 1) -> Event:
    return Event(type="snapshot", data={"currentPhase": phase, "currentRound": round_})


class ScriptedRole:
    """Returns the scripted results in order (an exception instance is raised) and counts decisions."""

    name = "owner"
    prompt_renderer = object()
    response_parser = object()

    def __init__(self, *results: Any) -> None:
        self.results = list(results)
        self.calls: list[str] = []

    async def handle_phase(self, phase, state, prompts_dir):
        self.calls.append(phase)
        result = self.results.pop(0) if self.results else None
        if isinstance(result, BaseException):
            raise result
        return result


class Transport:
    """Records sent frames; ``failures`` are raised by the next send attempts."""

    def __init__(self, *failures: BaseException) -> None:
        self.failures = list(failures)
        self.sent: list[str] = []

    async def start_listening(self) -> None:
        return None

    async def send(self, message: str) -> None:
        if self.failures:
            raise self.failures.pop(0)
        self.sent.append(message)

    async def stop(self) -> None:
        return None


class RecordingGate:
    """Durable-store stand-in for the ``decision_gate`` hook."""

    def __init__(self, decided: set[tuple[Any, Any]] | None = None) -> None:
        self.decided = set(decided or ())
        self.queries: list[tuple[Any, Any]] = []
        self.marks: list[tuple[tuple[Any, Any], str]] = []

    def is_decided(self, occurrence) -> bool:
        self.queries.append(tuple(occurrence))
        return tuple(occurrence) in self.decided

    def mark_decided(self, occurrence, outcome) -> None:
        self.marks.append((tuple(occurrence), outcome))
        self.decided.add(tuple(occurrence))


def make_agent(role: ScriptedRole, transport: Transport, tmp_path: Path, **kwargs: Any) -> Agent:
    return Agent(
        url="ws://unused",
        state=RoundGameState(),
        role=role,
        prompts_dir=tmp_path,
        transport=transport,
        phase_transition_event="snapshot",
        phase_identifier_key="currentPhase",
        phase_engine=PhaseEngine(continuous_phases={MARKET}, min_action_delay=3600, max_action_delay=3600),
        **kwargs,
    )


async def deliver(agent: Agent, event: Event) -> None:
    """Feed an event; an exception escaping the decision is part of the scenario, not the test."""
    try:
        await agent.on_event(event)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Gate: a completed decision is not taken again for the same occurrence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_sent_decision_is_not_redecided_on_same_occurrence_snapshot(tmp_path, caplog):
    role = ScriptedRole(declaration(70), declaration(55))
    transport = Transport()
    agent = make_agent(role, transport, tmp_path)

    await deliver(agent, snapshot(DECLARATION))
    with caplog.at_level(logging.INFO):
        await deliver(agent, snapshot(DECLARATION))

    assert role.calls == [DECLARATION], f"the occurrence was decided {len(role.calls)} times"
    assert transport.sent == [json.dumps(declaration(70))], f"the occurrence was submitted again: {transport.sent}"
    assert any(r.levelno == logging.INFO and GATE_LOG in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_gate_reconnect_snapshot_does_not_resubmit(tmp_path):
    """The futarchy re-join: player-joined -> get-snapshot -> snapshot of the phase already decided."""
    role = ScriptedRole(declaration(70), declaration(55))
    transport = Transport()
    agent = make_agent(role, transport, tmp_path)

    await deliver(agent, snapshot(DECLARATION))
    await deliver(agent, Event(type="declaration-received", data={"playerNumber": 3}))
    await deliver(agent, Event(type="player-joined", data={"playerNumber": 3}))
    await deliver(agent, snapshot(DECLARATION))
    await deliver(agent, snapshot(DECLARATION))

    assert len(role.calls) == 1
    assert transport.sent == [json.dumps(declaration(70))]


@pytest.mark.asyncio
async def test_gate_hold_counts_as_decided(tmp_path):
    """A decision that returns no action (a hold, or a result the role dropped) is complete."""
    role = ScriptedRole(None, declaration(55))
    transport = Transport()
    agent = make_agent(role, transport, tmp_path)

    await deliver(agent, snapshot(DECLARATION))
    await deliver(agent, snapshot(DECLARATION))

    assert len(role.calls) == 1, f"a held occurrence was decided {len(role.calls)} times"
    assert transport.sent == []


@pytest.mark.asyncio
async def test_gate_without_round_the_same_phase_id_is_one_occurrence(tmp_path):
    """Without ``state.meta.round`` a next round under the same phase id is the same occurrence."""
    role = ScriptedRole(declaration(70), declaration(55))
    transport = Transport()
    agent = make_agent(role, transport, tmp_path)
    agent.state = GameState()

    await deliver(agent, snapshot(DECLARATION, round_=1))
    await deliver(agent, snapshot(DECLARATION, round_=2))

    assert len(role.calls) == 1
    assert transport.sent == [json.dumps(declaration(70))]


# ---------------------------------------------------------------------------
# Guards: what must still be decided again
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_guard_untransmitted_action_is_decided_again_on_next_snapshot(tmp_path):
    """A send that raised ConnectionError never reached the server, so the next snapshot retries."""
    role = ScriptedRole(declaration(70), declaration(55))
    transport = Transport(ConnectionError("no open connection"))
    agent = make_agent(role, transport, tmp_path)

    await deliver(agent, snapshot(DECLARATION))
    assert transport.sent == []
    await deliver(agent, snapshot(DECLARATION))

    assert len(role.calls) == 2
    assert transport.sent == [json.dumps(declaration(55))]


@pytest.mark.asyncio
async def test_guard_failed_decision_is_decided_again_on_next_snapshot(tmp_path):
    role = ScriptedRole(RuntimeError("provider outage"), declaration(55))
    transport = Transport()
    agent = make_agent(role, transport, tmp_path)

    await deliver(agent, snapshot(DECLARATION))
    await deliver(agent, snapshot(DECLARATION))

    assert len(role.calls) == 2
    assert transport.sent == [json.dumps(declaration(55))]


@pytest.mark.asyncio
async def test_guard_same_phase_in_next_round_is_decided(tmp_path):
    role = ScriptedRole(declaration(70), declaration(70))
    transport = Transport()
    agent = make_agent(role, transport, tmp_path)

    await deliver(agent, snapshot(DECLARATION, round_=1))
    await deliver(agent, snapshot(DECLARATION, round_=2))

    assert len(role.calls) == 2
    assert transport.sent == [json.dumps(declaration(70))] * 2


@pytest.mark.asyncio
@pytest.mark.parametrize("between", [SPECULATION, MARKET])
async def test_guard_phase_entered_again_after_another_phase_is_decided(tmp_path, between):
    """The in-process gate resets when the occurrence changes, even if the next one has the same key."""
    role = ScriptedRole(declaration(70), None, declaration(70))
    transport = Transport()
    agent = make_agent(role, transport, tmp_path)
    try:
        await deliver(agent, snapshot(DECLARATION))
        await deliver(agent, snapshot(between))
        await deliver(agent, snapshot(DECLARATION))

        assert role.calls == [DECLARATION, between, DECLARATION]
        assert transport.sent == [json.dumps(declaration(70))] * 2
    finally:
        await agent.stop()


# ---------------------------------------------------------------------------
# Hook: Agent(decision_gate=...)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hook_records_sent_and_hold_outcomes_but_not_untransmitted_ones(tmp_path):
    gate = RecordingGate()
    role = ScriptedRole(declaration(70), None, declaration(1), declaration(2))
    transport = Transport()
    agent = make_agent(role, transport, tmp_path, decision_gate=gate)

    await deliver(agent, snapshot(DECLARATION, round_=1))
    await deliver(agent, snapshot(SPECULATION, round_=1))
    transport.failures.append(ConnectionError("socket closed"))
    await deliver(agent, snapshot(DECLARATION, round_=2))
    await deliver(agent, snapshot(DECLARATION, round_=2))

    assert gate.marks == [
        ((DECLARATION, 1), "sent"),
        ((SPECULATION, 1), "hold"),
        ((DECLARATION, 2), "sent"),
    ]
    assert transport.sent == [json.dumps(declaration(70)), json.dumps(declaration(2))]


@pytest.mark.asyncio
async def test_hook_stops_a_new_agent_deciding_an_occurrence_decided_elsewhere(tmp_path, caplog):
    """A durable gate covers what the in-memory gate cannot: a restarted process."""
    gate = RecordingGate({(DECLARATION, 1)})
    role = ScriptedRole(declaration(55))
    transport = Transport()
    agent = make_agent(role, transport, tmp_path, decision_gate=gate)

    with caplog.at_level(logging.INFO):
        await deliver(agent, snapshot(DECLARATION, round_=1))

    assert role.calls == []
    assert transport.sent == []
    assert any(r.levelno == logging.INFO and GATE_LOG in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_hook_is_not_used_for_continuous_phases(tmp_path):
    gate = RecordingGate({(MARKET, 1)})
    role = ScriptedRole(declaration(70))
    transport = Transport()
    agent = make_agent(role, transport, tmp_path, decision_gate=gate)
    try:
        await deliver(agent, snapshot(MARKET))
        await asyncio.sleep(0)

        assert role.calls == [MARKET]
        assert gate.queries == [] and gate.marks == []
    finally:
        await agent.stop()


class FailingGate(RecordingGate):
    def __init__(self, fail_on: str) -> None:
        super().__init__()
        self.fail_on = fail_on

    def is_decided(self, occurrence) -> bool:
        if self.fail_on == "is_decided":
            raise OSError("journal unreadable")
        return super().is_decided(occurrence)

    def mark_decided(self, occurrence, outcome) -> None:
        if self.fail_on == "mark_decided":
            raise OSError("journal unwritable")
        super().mark_decided(occurrence, outcome)


@pytest.mark.asyncio
async def test_hook_is_decided_error_is_logged_and_no_decision_is_made(tmp_path, caplog):
    role = ScriptedRole(declaration(70))
    transport = Transport()
    agent = make_agent(role, transport, tmp_path, decision_gate=FailingGate("is_decided"))

    with caplog.at_level(logging.ERROR):
        await agent.on_event(snapshot(DECLARATION))

    assert role.calls == []
    assert transport.sent == []
    assert any(r.levelno == logging.ERROR and "Decision gate failed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_hook_mark_decided_error_is_logged_and_the_in_memory_gate_still_holds(tmp_path, caplog):
    role = ScriptedRole(declaration(70), declaration(55))
    transport = Transport()
    agent = make_agent(role, transport, tmp_path, decision_gate=FailingGate("mark_decided"))

    with caplog.at_level(logging.ERROR):
        await agent.on_event(snapshot(DECLARATION))
        await agent.on_event(snapshot(DECLARATION))

    assert role.calls == [DECLARATION]
    assert transport.sent == [json.dumps(declaration(70))]
    assert any(r.levelno == logging.ERROR and "failed to record" in r.message for r in caplog.records)
