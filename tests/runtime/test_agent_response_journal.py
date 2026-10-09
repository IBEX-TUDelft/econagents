"""Reproduction for IBEX-game_suite#8: durable responses and recovery without a new model decision.

The agent must persist each response (with its response-slot identity) before sending it, record
whether it reached the wire and whether the server acknowledged it, and, after a crash or reconnect,
reuse the persisted response for that slot instead of asking the model again.

The proposed interface is named in exactly one place, ``_proposed_agent`` below; a fix that picks other
names only has to edit that function. The proposal is ``econagents.runtime.journal.ResponseJournal(dir)``
passed as ``Agent(response_journal=...)``, with two caller-supplied callables:
``response_slot(phase, state) -> slot id`` and ``response_ack(event, state) -> slot id | None``. Slot and
ack identity are the caller's because econagents does not know the game (the authoritative slot
identity is pending Yary, see the issue). When the proposal is absent the tests fall back to a plain
``Agent``, so they fail on behavior (model calls, wire bytes, journal contents), not on an import error.

Frames use the shapes futarchy-agents and the server emit on origin/futharcy-agents (``roles._envelope``,
``DeclareHandler``: ``declaration-received`` with ``{playerNumber}`` to every player on success).
"""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from econagents.domain import Event
from econagents.domain.state.game import GameState
from econagents.runtime import Agent, PhaseEngine

PLAYER = 2
RECOVERY = "rec-abc"
DECLARATION = "declaration_first"
MARKET = "market"


def _declaration(value: int) -> dict[str, Any]:
    return {
        "meta": {"type": "submit-declaration", "component": {"type": "standard:declaration"}},
        "payload": {"values": [{"condition": "no_project", "value": value}, {"condition": "project", "value": value}]},
    }


def _post_order(price: int) -> dict[str, Any]:
    return {
        "meta": {"type": "post-order", "component": {"type": "standard:dam", "name": "no_project"}},
        "payload": {"sender": PLAYER, "type": "bid", "price": price, "timestamp": 1791555677396 + price, "now": False},
    }


def _declaration_received(player: int) -> Event:
    return Event(type="declaration-received", data={"playerNumber": player})


def _snapshot(phase: str, round_: int = 1) -> Event:
    players = [{"playerNumber": PLAYER, "role": "developer", "recovery": RECOVERY}]
    return Event(type="snapshot", data={"currentRound": round_, "currentPhase": phase, "players": players})


class ProcessCrash(BaseException):
    """The process dies; nothing in the agent may catch this."""


class ScriptedRole:
    """Stands in for the LLM-backed role: returns scripted responses and counts model decisions."""

    name = "developer"
    prompt_renderer = object()
    response_parser = object()

    def __init__(self, *responses: dict[str, Any] | None):
        self.responses = list(responses)
        self.calls = 0

    async def handle_phase(self, phase, state, prompts_dir):
        self.calls += 1
        return self.responses.pop(0) if self.responses else None


class WireTransport:
    """Records what reached the wire. ``failures`` lists exceptions for the next send attempts."""

    def __init__(self, failures: list[BaseException] | None = None, on_send=None):
        self.failures = list(failures or [])
        self.on_send = on_send
        self.attempts: list[str] = []
        self.wire: list[str] = []

    async def start_listening(self) -> None:
        return None

    async def send(self, message: str):
        self.attempts.append(message)
        if self.on_send is not None:
            self.on_send(message)
        if self.failures:
            raise self.failures.pop(0)
        self.wire.append(message)
        return True

    async def stop(self) -> None:
        return None


class Slots:
    """Interim slot identity used by the tests: (game, round, phase, player)."""

    def __init__(self):
        self.round = 1

    def __call__(self, phase, state) -> str:
        return f"g1:r{self.round}:{phase}:p{PLAYER}"


class Acks:
    """The futharcy-agents ack for a sealed declaration: ``declaration-received`` for this player."""

    def __init__(self, slots: Slots):
        self.slots = slots

    def __call__(self, event, state) -> str | None:
        if event.type == "declaration-received" and event.data.get("playerNumber") == PLAYER:
            return self.slots(DECLARATION, state)
        return None


def _proposed_agent(base_kwargs: dict[str, Any], *, journal_dir: Path, slots: Slots) -> tuple[Agent, str]:
    """The single adapter point for the proposed API: edit only this to match the implemented names."""
    try:
        from econagents.runtime.journal import ResponseJournal

        journal = ResponseJournal(journal_dir)
        return Agent(**base_kwargs, response_journal=journal, response_slot=slots, response_ack=Acks(slots)), ""
    except (ImportError, TypeError) as exc:
        note = f" [proposed ResponseJournal/Agent(response_journal=, response_slot=, response_ack=) unavailable: {exc}]"
        return Agent(**base_kwargs), note


def _build_agent(
    *, role, transport, prompts_dir: Path, journal_dir: Path, slots: Slots, continuous: set[str] | None = None
) -> tuple[Agent, str]:
    kwargs: dict[str, Any] = dict(
        url="ws://127.0.0.1:1",
        state=GameState(),
        role=role,
        prompts_dir=prompts_dir,
        transport=transport,
        auth_mechanism_kwargs={"recovery": RECOVERY},
        phase_transition_event="snapshot",
        phase_identifier_key="currentPhase",
        phase_engine=PhaseEngine(continuous_phases=continuous or set(), min_action_delay=3600, max_action_delay=3600),
    )
    return _proposed_agent(kwargs, journal_dir=journal_dir, slots=slots)


def _json_values(node: Any):
    yield node
    if isinstance(node, dict):
        for value in node.values():
            yield from _json_values(value)
    elif isinstance(node, list):
        for value in node:
            yield from _json_values(value)


def _journal_holds(journal_dir: Path, frame: str) -> bool:
    """True when some file under ``journal_dir`` holds ``frame`` verbatim or as a JSON value."""
    if not journal_dir.exists():
        return False
    expected = json.loads(frame)
    for path in journal_dir.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(errors="replace")
        if frame in text:
            return True
        for chunk in [text, *text.splitlines()]:
            try:
                decoded = json.loads(chunk)
            except ValueError:
                continue
            if any(value == frame or value == expected for value in _json_values(decoded)):
                return True
    return False


async def _deliver(agent: Agent, event: Event) -> None:
    """Feed an event; a send failure surfacing as an exception is part of the scenario, not the test."""
    try:
        await agent.on_event(event)
    except Exception:
        pass


# --- interface-proposal checks ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_response_is_persisted_before_it_is_sent(tmp_path):
    journal_dir = tmp_path / "journal"
    persisted_when_sent: list[bool] = []
    transport = WireTransport(on_send=lambda frame: persisted_when_sent.append(_journal_holds(journal_dir, frame)))
    role = ScriptedRole(_declaration(70))
    agent, note = _build_agent(
        role=role, transport=transport, prompts_dir=tmp_path, journal_dir=journal_dir, slots=Slots()
    )

    await _deliver(agent, _snapshot(DECLARATION))

    files = [p for p in journal_dir.rglob("*") if p.is_file()] if journal_dir.exists() else []
    assert transport.wire == [json.dumps(_declaration(70))]
    assert persisted_when_sent == [True], (
        f"the response reached the wire before it was persisted (journal dir holds {len(files)} file(s)){note}"
    )


@pytest.mark.asyncio
async def test_crash_after_persist_before_transmit_resends_saved_bytes_without_model_call(tmp_path):
    journal_dir = tmp_path / "journal"
    slots = Slots()
    first_role = ScriptedRole(_declaration(70))
    crashing = WireTransport(failures=[ProcessCrash()])
    first, note = _build_agent(
        role=first_role, transport=crashing, prompts_dir=tmp_path, journal_dir=journal_dir, slots=slots
    )
    with pytest.raises(ProcessCrash):
        await first.on_event(_snapshot(DECLARATION))
    assert crashing.wire == []
    persisted = crashing.attempts[0]
    del first

    restarted_role = ScriptedRole(_declaration(55))
    transport = WireTransport()
    restarted, _ = _build_agent(
        role=restarted_role, transport=transport, prompts_dir=tmp_path, journal_dir=journal_dir, slots=slots
    )
    await _deliver(restarted, _snapshot(DECLARATION))

    assert restarted_role.calls == 0, (
        f"after the crash the agent asked the model {restarted_role.calls} time(s) for a slot whose response "
        f"was already persisted{note}"
    )
    assert transport.wire == [persisted], (
        f"recovery sent {transport.wire} instead of exactly the persisted bytes {[persisted]}{note}"
    )


@pytest.mark.asyncio
async def test_hold_response_is_persisted_and_recovered_without_model_call(tmp_path):
    journal_dir = tmp_path / "journal"
    slots = Slots()
    holding_role = ScriptedRole(None)
    first_transport = WireTransport()
    first, note = _build_agent(
        role=holding_role, transport=first_transport, prompts_dir=tmp_path, journal_dir=journal_dir, slots=slots
    )
    await _deliver(first, _snapshot(DECLARATION))
    assert holding_role.calls == 1 and first_transport.wire == []
    del first

    restarted_role = ScriptedRole(_declaration(55))
    transport = WireTransport()
    restarted, _ = _build_agent(
        role=restarted_role, transport=transport, prompts_dir=tmp_path, journal_dir=journal_dir, slots=slots
    )
    await _deliver(restarted, _snapshot(DECLARATION))

    assert restarted_role.calls == 0, (
        f"after a restart the agent asked the model {restarted_role.calls} time(s) for a slot it had already "
        f"answered with a deliberate hold{note}"
    )
    assert transport.wire == [], f"a recovered hold put {transport.wire} on the wire{note}"


@pytest.mark.asyncio
async def test_lost_request_is_retransmitted_once_without_new_decision(tmp_path):
    role = ScriptedRole(_declaration(70), _declaration(55))
    transport = WireTransport(failures=[ConnectionError("socket closed before the frame was written")])
    agent, note = _build_agent(
        role=role, transport=transport, prompts_dir=tmp_path, journal_dir=tmp_path / "journal", slots=Slots()
    )

    await _deliver(agent, _snapshot(DECLARATION))
    assert transport.wire == []
    await _deliver(agent, _snapshot(DECLARATION))

    assert role.calls == 1, (
        f"the model was asked {role.calls} times for one declaration slot; the lost request must be "
        f"retransmitted from the persisted response{note}"
    )
    assert transport.wire == [json.dumps(_declaration(70))], (
        f"after reconnect the wire got {transport.wire}, not one retransmission of the original bytes{note}"
    )


@pytest.mark.asyncio
async def test_lost_request_is_retransmitted_after_restart_without_new_decision(tmp_path):
    """A send that raised is recorded as not transmitted, so a restarted agent still resends it."""
    journal_dir = tmp_path / "journal"
    slots = Slots()
    first_role = ScriptedRole(_declaration(70))
    failing = WireTransport(failures=[ConnectionError("socket closed before the frame was written")])
    first, note = _build_agent(
        role=first_role, transport=failing, prompts_dir=tmp_path, journal_dir=journal_dir, slots=slots
    )
    await _deliver(first, _snapshot(DECLARATION))
    assert failing.wire == [] and first_role.calls == 1
    del first

    restarted_role = ScriptedRole(_declaration(55))
    transport = WireTransport()
    restarted, _ = _build_agent(
        role=restarted_role, transport=transport, prompts_dir=tmp_path, journal_dir=journal_dir, slots=slots
    )
    await _deliver(restarted, _snapshot(DECLARATION))

    assert restarted_role.calls == 0, (
        f"after a restart the agent asked the model {restarted_role.calls} time(s) for a slot whose request "
        f"never reached the wire{note}"
    )
    assert transport.wire == [json.dumps(_declaration(70))], (
        f"after a restart the wire got {transport.wire}: a failed send must stay 'not transmitted' and be "
        f"resent from the persisted bytes{note}"
    )


@pytest.mark.asyncio
async def test_acked_slot_is_neither_redecided_nor_resent(tmp_path):
    """After the server's own-player ack, a same-phase re-snapshot (each reconnect's player-joined ->
    get-snapshot) must not ask the model or resend: DeclareHandler would answer 'declaration-refused'."""
    role = ScriptedRole(_declaration(70), _declaration(55))
    transport = WireTransport()
    agent, note = _build_agent(
        role=role, transport=transport, prompts_dir=tmp_path, journal_dir=tmp_path / "journal", slots=Slots()
    )

    await _deliver(agent, _snapshot(DECLARATION))
    await _deliver(agent, _declaration_received(5))
    await _deliver(agent, _declaration_received(PLAYER))
    await _deliver(agent, _snapshot(DECLARATION))

    original = json.dumps(_declaration(70))
    assert role.calls == 1, f"an acknowledged slot triggered {role.calls} model decisions{note}"
    assert transport.wire == [original], (
        f"after the server acknowledged the declaration the wire got {transport.wire}, not only {[original]}{note}"
    )


@pytest.mark.asyncio
async def test_acked_slot_is_not_resent_after_restart(tmp_path):
    journal_dir = tmp_path / "journal"
    slots = Slots()
    first_transport = WireTransport()
    first, note = _build_agent(
        role=ScriptedRole(_declaration(70)),
        transport=first_transport,
        prompts_dir=tmp_path,
        journal_dir=journal_dir,
        slots=slots,
    )
    await _deliver(first, _snapshot(DECLARATION))
    await _deliver(first, _declaration_received(PLAYER))
    assert first_transport.wire == [json.dumps(_declaration(70))]
    del first

    restarted_role = ScriptedRole(_declaration(55))
    transport = WireTransport()
    restarted, _ = _build_agent(
        role=restarted_role, transport=transport, prompts_dir=tmp_path, journal_dir=journal_dir, slots=slots
    )
    await _deliver(restarted, _snapshot(DECLARATION))

    assert restarted_role.calls == 0, (
        f"after a restart the agent asked the model {restarted_role.calls} time(s) for an acknowledged slot{note}"
    )
    assert transport.wire == [], f"after a restart an acknowledged slot was resent: {transport.wire}{note}"


@pytest.mark.asyncio
async def test_unconfirmed_slot_gets_no_new_decision(tmp_path):
    """Sent but not acknowledged (lost ack, or ack not yet seen): whatever the recovery policy (identical
    retry or slot-status query, pending Yary), the model is not asked again and nothing but the
    persisted bytes may reach the wire for that slot."""
    role = ScriptedRole(_declaration(70), _declaration(55))
    transport = WireTransport()
    agent, note = _build_agent(
        role=role, transport=transport, prompts_dir=tmp_path, journal_dir=tmp_path / "journal", slots=Slots()
    )

    await _deliver(agent, _snapshot(DECLARATION))
    await _deliver(agent, _snapshot(DECLARATION))

    original = json.dumps(_declaration(70))
    assert role.calls == 1, f"an unacknowledged slot triggered {role.calls} model decisions{note}"
    assert set(transport.wire) == {original}, (
        f"for one unacknowledged slot the wire got {transport.wire}; only the persisted bytes {original} may be sent{note}"
    )


# --- decision-gated (Yary: identical retry vs slot-status query; server idempotency) -------------
# Not part of the fx spec until the decision is made; un-skip it if Yary picks identical retry.


@pytest.mark.skip(reason="decision-gated on Yary (IBEX-game_suite#8): identical retry vs slot-status query")
@pytest.mark.asyncio
async def test_lost_ack_retries_identical_bytes_for_same_slot(tmp_path):
    """Assumes the server answers an identical retry for the same slot with an idempotent result. On
    origin/futharcy-agents DeclareHandler refuses it ('declaration-refused' already-submitted), and the
    alternative is a slot-status query."""
    role = ScriptedRole(_declaration(70), _declaration(55))
    transport = WireTransport()
    agent, note = _build_agent(
        role=role, transport=transport, prompts_dir=tmp_path, journal_dir=tmp_path / "journal", slots=Slots()
    )

    await _deliver(agent, _snapshot(DECLARATION))
    await _deliver(agent, _snapshot(DECLARATION))

    original = json.dumps(_declaration(70))
    assert role.calls == 1, f"an unacknowledged slot triggered {role.calls} model decisions{note}"
    assert transport.wire == [original, original], (
        f"after a lost ack the wire got {transport.wire}, not an identical retry of {original}{note}"
    )


# --- guards (expected to pass before and after the fix) -----------------------------------------


@pytest.mark.asyncio
async def test_identical_payload_for_independent_slot_is_sent_again(tmp_path):
    """Idempotency is keyed on slot identity, never on payload equality."""
    slots = Slots()
    role = ScriptedRole(_declaration(70), _declaration(70))
    transport = WireTransport()
    agent, _ = _build_agent(
        role=role, transport=transport, prompts_dir=tmp_path, journal_dir=tmp_path / "journal", slots=slots
    )

    await _deliver(agent, _snapshot(DECLARATION, round_=1))
    slots.round = 2
    await _deliver(agent, _snapshot(DECLARATION, round_=2))

    frame = json.dumps(_declaration(70))
    assert role.calls == 2
    assert transport.wire == [frame, frame]


@pytest.mark.asyncio
async def test_uncertain_market_order_is_not_blindly_resent(tmp_path):
    """Until the server has response-slot identity for the market, a post-order whose ack is uncertain
    must not be resent: PostOrderHandler has no dedup, so a resend is a second order and reservation."""
    role = ScriptedRole(_post_order(1041), _post_order(1042))
    transport = WireTransport()
    agent, _ = _build_agent(
        role=role,
        transport=transport,
        prompts_dir=tmp_path,
        journal_dir=tmp_path / "journal",
        slots=Slots(),
        continuous={MARKET},
    )
    tasks_before = asyncio.all_tasks()
    try:
        await _deliver(agent, _snapshot(MARKET))
        await _deliver(agent, _snapshot(MARKET))
        await asyncio.sleep(0.05)

        first = json.dumps(_post_order(1041))
        assert transport.wire.count(first) == 1, f"the uncertain post-order was resent: {transport.wire}"
    finally:
        await agent.stop()
        leftovers = [t for t in asyncio.all_tasks() - tasks_before if t is not asyncio.current_task()]
        for task in leftovers:
            task.cancel()
        await asyncio.gather(*leftovers, return_exceptions=True)
