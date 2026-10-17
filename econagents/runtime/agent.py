"""Agent runtime for one simulated player."""

import asyncio
import logging
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Literal, Optional

from econagents.adapters.protocol import INTRODUCTION_PHASE, IbexMessageCodec, ready_message
from econagents.adapters.parsing import JsonResponseParser
from econagents.adapters.prompts import JinjaPromptRenderer
from econagents.adapters.state import EventFieldStateProjector
from econagents.adapters.transport import AuthenticationMechanism, JoinPayloadAuth, WebSocketTransport
from econagents.domain.role import Role
from econagents.domain.logging import LoggerMixin
from econagents.runtime.decision_gate import DecisionGate, DecisionOutcome, PhaseOccurrence
from econagents.runtime.identity import (
    PLAYER_JOINED_EVENT,
    SNAPSHOT_EVENT,
    IdentityMismatchError,
    PlayerIdentity,
    json_record,
)
from econagents.runtime.dispositions import (
    DecisionInputMode,
    DecisionTrace,
    DispositionTracker,
    InputRevision,
    UnknownPolicy,
    is_unknown,
    state_revision,
)
from econagents.runtime.phase_engine import PhaseEngine
from econagents.domain.messages import Event, PhaseId
from econagents.domain.state.game import GameState
from econagents.ports.codec import MessageCodec, MessageDecodeError
from econagents.ports.state import StateProjectorPort
from econagents.ports.transport import TransportPort

PhaseHandler = Callable[[PhaseId, GameState], Any]
EventHandler = Callable[[Event], Any]

ActionStatus = Literal["sent", "not-transmitted", "stale", "no-action", "skipped", "superseded"]


@dataclass(frozen=True)
class ActionOutcome:
    """What became of one phase decision.

    ``status`` is ``"sent"`` when the transport accepted the frame, ``"not-transmitted"`` when it raised
    ``ConnectionError`` (``error`` holds it), ``"stale"`` when the decision finished after the agent had
    moved to another phase occurrence or stopped (nothing is sent), ``"no-action"`` when the handler or
    role returned no action, ``"skipped"`` when the phase ended before the decision started, and
    ``"superseded"`` when a revision guard (``Agent(decision_input="guard-...")``) discarded the action
    because the state changed during the decision. ``decision_id`` identifies the decision in the
    decision trace. ``disposition`` is set once the decision is settled: always for outcomes other than
    ``"sent"``, and for ``"sent"`` only when no disposition tracker waits for the server's answer.
    """

    phase: PhaseId
    status: ActionStatus
    payload: Optional[dict[str, Any]] = None
    frame: Optional[str] = None
    error: Optional[BaseException] = None
    decision_id: Optional[str] = None
    disposition: Optional[str] = None

    @property
    def transmitted(self) -> bool:
        """Whether the action's frame was handed to the transport without error."""
        return self.status == "sent"


ActionListener = Callable[[ActionOutcome], Any]


class Agent(LoggerMixin):
    """Run one agent against a game server.

    A non-continuous phase occurrence is decided at most once per ``Agent`` instance: once its decision
    has completed (the action was sent, or the handler or role returned no action), a later transition
    into the same occurrence, such as the snapshot replayed after a reconnect, is logged at INFO and
    ignored. A decision that raised, was cancelled, was dropped as stale, or whose send raised
    ``ConnectionError`` does not count, so the next transition into the occurrence decides again. Pass
    ``decision_gate`` to also consult and update a store that outlives the process; without one, a
    restarted agent decides again.

    The agent binds the seat the server authenticated it as (``bound_identity``) from, in order of
    preference, the snapshot's own ``playerNumber`` and ``role``, the first ``player-joined`` received
    after each join, and the roster entry carrying its recovery token. It fills in
    ``state.meta.player_number`` when that is unset; when it was set before ``start()`` (the configured
    seat) and the server binds another seat or role, the agent logs ``identity_error`` and stops.
    ``instance_id`` identifies this agent instance; a replacement instance for the same seat gets a new one.

    Dispositions: with a ``disposition_tracker`` (see ``DispositionTracker``), an action the tracker
    announces as awaiting an answer stays unresolved until the tracker reports its disposition, and the
    agent's next decision, in any phase, does not start before that. ``disposition_timeout`` (seconds,
    ``None`` waits indefinitely) turns a missing answer into ``"unknown"``. The tracker reconciles an
    ``"unknown"`` decision by reporting its id again with a disposition that is not unknown; a further
    ``"unknown"`` for it changes nothing. With ``on_unknown="block"`` (the default) an ``"unknown"``
    disposition holds every later decision in its phase occurrence until the tracker reconciles it; no
    event releases it by itself. When the agent moves to a different phase occurrence, the action's
    phase has closed and the next decision reads that occurrence's state, so an unknown decision from an
    earlier occurrence stops blocking and keeps its ``"unknown"`` disposition (assumed, pending
    Rutger/Sander; IBEX-game_suite#37). Meanwhile ``reconcile_request`` (if given) is called at once and
    then every ``reconcile_retry_interval`` seconds, at most ``reconcile_retry_limit`` times.
    ``on_unknown="continue"`` only records it.

    Decision input: with ``decision_input="frozen"`` (the default) the role and phase handlers decide on
    a deep copy of the state taken when the decision starts, so events that arrive during the model call
    do not change its input. ``"guard-discard"`` drops the action when the state's revision changed
    during the decision, and ``"guard-rerun"`` decides once more on the new state first. Revisions come
    from ``input_revision`` (default: sha256 of the state's JSON form).

    ``decision_trace`` receives one record per decision once it is settled: ``decision_id``, ``phase``,
    ``round``, ``phase_epoch``, ``input_revision``, ``send_revision``, ``input_changed_during_call``,
    ``submitted`` (the frame, or ``None``), ``status`` (the ``ActionOutcome`` status) and
    ``disposition`` (the tracker's answer, ``"unknown"``, ``"sent"`` without a tracker, ``"no-action"``,
    ``"stale-phase"``, ``"not-transmitted"`` or ``"superseded"``). A decision whose disposition was unknown
    gets a second record when the tracker reconciles it, with the reconciled ``disposition`` and
    ``reconciled_from`` set to the unknown one, or, under ``on_unknown="block"``, when its phase
    occurrence ends unreconciled, with the unknown ``disposition`` and ``unresolved_at_phase_close``
    set to ``True``.
    """

    def __init__(
        self,
        *,
        url: str,
        state: GameState,
        role: Role,
        prompts_dir: Path,
        phase_transition_event: str = "phase-transition",
        phase_identifier_key: str = "phase",
        phase_engine: PhaseEngine | None = None,
        message_codec: MessageCodec | None = None,
        state_projector: StateProjectorPort | None = None,
        auth_mechanism: AuthenticationMechanism | None = None,
        auth_mechanism_kwargs: dict[str, Any] | None = None,
        end_game_event: str = "game-over",
        logger: logging.Logger | None = None,
        transport: TransportPort | None = None,
        decision_gate: DecisionGate | None = None,
        disposition_tracker: DispositionTracker | None = None,
        disposition_timeout: float | None = None,
        decision_trace: DecisionTrace | None = None,
        on_unknown: UnknownPolicy = "block",
        reconcile_request: Callable[[], Any] | None = None,
        reconcile_retry_interval: float = 2.0,
        reconcile_retry_limit: int = 3,
        decision_input: DecisionInputMode = "frozen",
        input_revision: InputRevision | None = None,
    ) -> None:
        if on_unknown not in ("block", "continue"):
            raise ValueError(f"on_unknown must be 'block' or 'continue', not {on_unknown!r}")
        if decision_input not in ("frozen", "guard-discard", "guard-rerun"):
            raise ValueError(
                f"decision_input must be 'frozen', 'guard-discard' or 'guard-rerun', not {decision_input!r}"
            )
        if disposition_timeout is not None and disposition_timeout <= 0:
            raise ValueError(f"disposition_timeout must be positive or None, not {disposition_timeout!r}")
        if logger:
            self.logger = logger

        self.url = url
        self.state = state
        self.role = role
        if self.role.prompt_renderer is None:
            self.role.prompt_renderer = JinjaPromptRenderer()
        if self.role.response_parser is None:
            self.role.response_parser = JsonResponseParser()
        self.prompts_dir = prompts_dir
        self.phase_transition_event = phase_transition_event
        self.phase_identifier_key = phase_identifier_key
        self.phase_engine = phase_engine or PhaseEngine()
        self.message_codec = message_codec or IbexMessageCodec()
        self.state_projector = state_projector or EventFieldStateProjector()
        self.auth_mechanism = auth_mechanism or JoinPayloadAuth()
        self.auth_mechanism_kwargs = auth_mechanism_kwargs or {}
        self.end_game_event = end_game_event
        self.decision_gate = decision_gate
        self.instance_id = uuid.uuid4().hex
        self.bound_identity: PlayerIdentity | None = None
        self.identity_error: IdentityMismatchError | None = None
        self._configured_player_number: Any = None
        self._configured_role: Any = None
        self._joined_connection: Any = None
        self._player_joined_seen = False
        self.disposition_tracker = disposition_tracker
        self.disposition_timeout = disposition_timeout
        self.decision_trace = decision_trace
        self.on_unknown = on_unknown
        self.reconcile_request = reconcile_request
        self.reconcile_retry_interval = reconcile_retry_interval
        self.reconcile_retry_limit = reconcile_retry_limit
        self.decision_input = decision_input
        self.input_revision = input_revision or state_revision
        self.transport = transport or WebSocketTransport(
            url=self.url,
            logger=self.logger,
            auth_mechanism=self.auth_mechanism,
            auth_mechanism_kwargs=self.auth_mechanism_kwargs,
            on_message_callback=self._raw_message_received,
        )
        self.running = False
        self.current_phase: PhaseId | None = None
        self.in_continuous_phase = False
        self._continuous_task: asyncio.Task | None = None
        self._entry_task: asyncio.Task | None = None
        self._phase_epoch = 0
        self._phase_occurrence: PhaseOccurrence | None = None
        self._decided_occurrence: PhaseOccurrence | None = None
        self._decision_lock = asyncio.Lock()
        self._decision_owner: asyncio.Task | None = None
        self._event_handlers: dict[str, list[EventHandler]] = {}
        self._action_listeners: list[ActionListener] = []
        self._pending: dict[str, dict[str, Any]] = {}
        self._disposition_timers: dict[str, asyncio.Task] = {}
        self._settled = asyncio.Event()
        self._unknown: dict[str, dict[str, Any]] = {}
        self._reconcile_task: asyncio.Task | None = None
        self._phase_handlers: dict[PhaseId, PhaseHandler] = {
            INTRODUCTION_PHASE: self._handle_introduction,
        }

    @property
    def llm_provider(self):
        """Return the LLM provider used by the role."""
        return getattr(self.role, "llm", None)

    def register_event_handler(self, event_type: str, handler: EventHandler) -> "Agent":
        """Register a handler that runs after state projection."""
        self._event_handlers.setdefault(event_type, []).append(handler)
        return self

    def register_action_listener(self, listener: ActionListener) -> "Agent":
        """Register a callback that receives the ``ActionOutcome`` of every phase decision.

        It runs after the send attempt, for decisions started by a phase transition, by the continuous
        loop or by ``execute_phase_action``. Exceptions it raises are logged and ignored.
        """
        self._action_listeners.append(listener)
        return self

    def register_phase_handler(self, phase: PhaseId, handler: PhaseHandler) -> "Agent":
        """Register a handler for a phase."""
        self._phase_handlers[phase] = handler
        return self

    async def start(self) -> None:
        """Connect to the game server and process events until stopped."""
        self.role.logger = self.logger
        meta = getattr(self.state, "meta", None)
        self._configured_player_number = getattr(meta, "player_number", None)
        self._configured_role = getattr(meta, "role", None)
        self.running = True
        await self.transport.start_listening()

    async def stop(self) -> None:
        """Stop the agent and transport."""
        self.running = False
        self._phase_epoch += 1
        self._cancel_phase_tasks()
        for timer in self._disposition_timers.values():
            timer.cancel()
        self._disposition_timers.clear()
        if self._reconcile_task is not None:
            self._reconcile_task.cancel()
            self._reconcile_task = None
        await self.transport.stop()

    async def _raw_message_received(self, raw_message: str) -> None:
        """Decode and dispatch a raw transport message."""
        try:
            event = self.message_codec.decode_event(raw_message)
        except MessageDecodeError as exc:
            self.logger.error(str(exc))
            return
        asyncio.create_task(self.on_event(event))

    async def on_event(self, event: Event) -> None:
        """Project an event into state and run the relevant behavior."""
        self.logger.debug(f"<-- Agent received event: {event}")
        self.state_projector.apply(self.state, event)
        if not self._resolve_player_number(event):
            await self.stop()
            return
        self._observe_dispositions(event)

        for handler in self._event_handlers.get(event.type, []):
            result = handler(event)
            if hasattr(result, "__await__"):
                await result

        if event.type == self.end_game_event:
            await self.stop()
            return

        if event.type == self.phase_transition_event:
            await self.handle_phase_transition(event.data.get(self.phase_identifier_key))

    async def handle_phase_transition(self, phase: PhaseId | None) -> None:
        """Move to a new phase and execute the appropriate action behavior.

        A phase occurrence is identified by the phase id and, when the state has one, ``state.meta.round``.
        A transition into the current occurrence does not start a new decision while one is in flight or
        while that phase's continuous loop is running. For a non-continuous phase it also does not start
        one once the occurrence's decision has completed (see ``decision_gate``). A transition into a
        different occurrence cancels the previous one's pending decision and loop. Must not be awaited
        from inside a phase decision.
        """
        if self._decision_owner is not None and self._decision_owner is asyncio.current_task():
            raise RuntimeError("handle_phase_transition cannot be awaited from inside a phase decision")

        occurrence = PhaseOccurrence(phase, self._current_round())
        if occurrence == self._phase_occurrence:
            if self._phase_busy():
                self.logger.info(
                    f"Ignoring transition into phase {phase}: the agent is already in it and its decision or loop "
                    "is active"
                )
                return
        else:
            self._phase_epoch += 1
            self._cancel_phase_tasks()
            self._decided_occurrence = None
            self._release_closed_unknowns()

        self.current_phase = phase
        self._phase_occurrence = occurrence
        if phase is None:
            return
        if not self.phase_engine.is_continuous(phase):
            try:
                decided = self._occurrence_decided(occurrence)
            except Exception:
                self.logger.exception(
                    f"Decision gate failed for phase {phase} (round {occurrence.round}); not deciding on this transition"
                )
                return
            if decided:
                self.logger.info(
                    f"Ignoring transition into phase {phase} (round {occurrence.round}): its decision already completed"
                )
                return

        epoch = self._phase_epoch
        entry = asyncio.create_task(self._execute_phase_action(phase, epoch))
        self._entry_task = entry
        if self.phase_engine.is_continuous(phase):
            self.in_continuous_phase = True
            self._continuous_task = asyncio.create_task(self._continuous_phase_loop(phase, epoch, entry))

        try:
            await asyncio.wait({entry})
        except asyncio.CancelledError:
            entry.cancel()
            raise
        if not entry.cancelled():
            entry.result()

    async def execute_phase_action(self, phase: PhaseId) -> ActionOutcome:
        """Execute one action for a phase and return what became of it.

        Decisions are single-flight per agent: this waits until no other decision is in flight, except
        when called from inside a phase handler or role decision, where it runs inline. The result is
        dropped instead of sent if the agent moves to another phase occurrence, or stops, while it is
        being decided (status ``"stale"``). If the transport raises ``ConnectionError`` while sending,
        the action is logged at ERROR as not transmitted, is not retried, and the outcome has status
        ``"not-transmitted"`` (``transmitted`` is ``False``). A completed decision for the current
        non-continuous phase occurrence is recorded in the decision gate.
        """
        return await self._execute_phase_action(phase, self._phase_epoch)

    async def _execute_phase_action(self, phase: PhaseId, epoch: int) -> ActionOutcome:
        current = asyncio.current_task()
        if self._decision_owner is not None and self._decision_owner is current:
            return await self._decide_and_send(phase, epoch)
        async with self._decision_lock:
            self._decision_owner = current
            try:
                return await self._decide_and_send(phase, epoch)
            finally:
                self._decision_owner = None

    async def _decide_and_send(self, phase: PhaseId, epoch: int) -> ActionOutcome:
        if epoch != self._phase_epoch:
            self.logger.debug(f"Skipping decision for phase {phase}: the phase ended before it started")
            return ActionOutcome(phase, "skipped")
        await self._wait_until_settled()
        if epoch != self._phase_epoch:
            self.logger.debug(f"Skipping decision for phase {phase}: the phase ended while it waited for a disposition")
            return ActionOutcome(phase, "skipped")
        occurrence = self._gated_occurrence(phase)
        decision_id = uuid.uuid4().hex
        record = self._new_trace_record(decision_id, phase, epoch)
        reruns_left = 1 if self.decision_input == "guard-rerun" else 0

        while True:
            input_revision = self._revision()
            record["input_revision"] = input_revision
            try:
                payload = await self._decide(phase)
            except asyncio.CancelledError:
                if epoch != self._phase_epoch:
                    record.update(status="stale", disposition="stale-phase")
                    self._emit_trace(record)
                raise
            send_revision = self._revision()
            record.update(
                send_revision=send_revision,
                input_changed_during_call=None if input_revision is None else input_revision != send_revision,
            )
            if epoch != self._phase_epoch:
                if payload:
                    self.logger.warning(
                        f"Dropping stale action decided in phase {phase}; the agent is now in phase {self.current_phase}"
                    )
                    outcome = ActionOutcome(phase, "stale", payload, decision_id=decision_id)
                    return await self._settle(outcome, record, "stale-phase")
                return await self._settle(
                    ActionOutcome(phase, "no-action", decision_id=decision_id), record, "no-action"
                )
            if not payload:
                self._record_decided(occurrence, epoch, "hold")
                return await self._settle(
                    ActionOutcome(phase, "no-action", decision_id=decision_id), record, "no-action"
                )
            if self.decision_input == "frozen" or not record["input_changed_during_call"]:
                break
            if reruns_left:
                reruns_left -= 1
                self.logger.info(f"State changed while deciding in phase {phase}; deciding again on the new state")
                continue
            self.logger.warning(
                f"Discarding the action decided in phase {phase}: the state changed during the decision"
            )
            outcome = ActionOutcome(phase, "superseded", payload, decision_id=decision_id)
            return await self._settle(outcome, record, "superseded")

        frame = self.message_codec.encode_action(payload)
        record["submitted"] = frame
        awaited = self._announce(decision_id, payload, record)
        try:
            await self.transport.send(frame)
        except ConnectionError as exc:
            if awaited:
                self._withdraw(decision_id)
            self.logger.error(f"Action decided in phase {phase} was not transmitted ({exc}): {frame}")
            outcome = ActionOutcome(phase, "not-transmitted", payload, frame, exc, decision_id=decision_id)
            return await self._settle(outcome, record, "not-transmitted")
        self._record_decided(occurrence, epoch, "sent")
        outcome = ActionOutcome(phase, "sent", payload, frame, decision_id=decision_id)
        if awaited:
            return await self._notify(outcome)
        return await self._settle(outcome, record, "sent")

    async def _decide(self, phase: PhaseId) -> Any:
        state = self.state.model_copy(deep=True) if self.decision_input == "frozen" else self.state
        if phase in self._phase_handlers:
            return await self._phase_handlers[phase](phase, state)
        return await self.role.handle_phase(phase, state, self.prompts_dir)

    def _revision(self) -> str | None:
        if self.decision_trace is None and self.decision_input == "frozen":
            return None
        try:
            return self.input_revision(self.state)
        except Exception:
            self.logger.exception("Could not compute the decision-input revision")
            return None

    def _new_trace_record(self, decision_id: str, phase: PhaseId, epoch: int) -> dict[str, Any]:
        return {
            "decision_id": decision_id,
            "phase": phase,
            "round": self._current_round(),
            "phase_epoch": epoch,
            "input_revision": None,
            "send_revision": None,
            "input_changed_during_call": None,
            "submitted": None,
            "status": None,
            "disposition": None,
        }

    async def _settle(self, outcome: ActionOutcome, record: dict[str, Any], disposition: str) -> ActionOutcome:
        record.update(status=outcome.status, disposition=disposition)
        self._emit_trace(record)
        return await self._notify(replace(outcome, disposition=disposition))

    def _emit_trace(self, record: dict[str, Any]) -> None:
        if self.decision_trace is None:
            return
        try:
            result = self.decision_trace(dict(record))
            if hasattr(result, "__await__"):
                asyncio.ensure_future(result)
        except Exception:
            self.logger.exception(f"Decision trace failed for decision {record.get('decision_id')}")

    def _announce(self, decision_id: str, payload: dict[str, Any], record: dict[str, Any]) -> bool:
        """Tell the tracker about a submission; return whether its disposition must be awaited."""
        if self.disposition_tracker is None:
            return False
        try:
            awaited = bool(self.disposition_tracker.submitted(decision_id, payload, self.state))
        except Exception:
            self.logger.exception(f"Disposition tracker failed on submission {decision_id}; not waiting for it")
            return False
        if not awaited:
            return False
        record["status"] = "sent"
        self._pending[decision_id] = record
        if self.disposition_timeout is not None:
            self._disposition_timers[decision_id] = asyncio.create_task(self._expire(decision_id))
        return True

    def _withdraw(self, decision_id: str) -> None:
        self._pending.pop(decision_id, None)
        timer = self._disposition_timers.pop(decision_id, None)
        if timer is not None:
            timer.cancel()
        not_transmitted = getattr(self.disposition_tracker, "not_transmitted", None)
        if callable(not_transmitted):
            try:
                not_transmitted(decision_id)
            except Exception:
                self.logger.exception(f"Disposition tracker failed on the untransmitted submission {decision_id}")
        self._settled.set()

    async def _expire(self, decision_id: str) -> None:
        await asyncio.sleep(self.disposition_timeout or 0)
        if decision_id in self._pending:
            self.logger.warning(
                f"No disposition for submission {decision_id} within {self.disposition_timeout}s; recording it as unknown"
            )
            self._resolve(decision_id, "unknown")

    def _observe_dispositions(self, event: Event) -> None:
        if self.disposition_tracker is None:
            return
        try:
            resolved = list(self.disposition_tracker.observe(event, self.state) or [])
        except Exception:
            self.logger.exception(f"Disposition tracker failed on a {event.type!r} event")
            return
        for decision_id, disposition in resolved:
            self._resolve(decision_id, disposition)

    @property
    def _blocked_on_unknown(self) -> bool:
        return self.on_unknown == "block" and bool(self._unknown)

    def _resolve(self, decision_id: str, disposition: str) -> None:
        record = self._pending.pop(decision_id, None)
        timer = self._disposition_timers.pop(decision_id, None)
        if timer is not None and timer is not asyncio.current_task():
            timer.cancel()
        if record is None:
            self._reconcile(decision_id, disposition)
            return
        record["disposition"] = disposition
        self._emit_trace(record)
        if is_unknown(disposition):
            self._unknown[decision_id] = record
            if self.on_unknown == "block":
                self._block_on_unknown()
        self._settled.set()

    def _reconcile(self, decision_id: str, disposition: str) -> None:
        """Settle an unknown decision the tracker reports again; release the block once none is left."""
        record = self._unknown.get(decision_id)
        if record is None or is_unknown(disposition):
            return
        del self._unknown[decision_id]
        self._emit_trace({**record, "disposition": disposition, "reconciled_from": record["disposition"]})
        self.logger.info(f"The disposition tracker reconciled the unknown decision {decision_id}: {disposition}")
        if self.on_unknown == "block" and not self._unknown:
            self._unblock()

    def _release_closed_unknowns(self) -> None:
        """Stop blocking on unknown decisions whose phase occurrence has ended; they stay unknown."""
        if self.on_unknown != "block":
            return
        closed = [d for d, r in self._unknown.items() if r.get("phase_epoch") != self._phase_epoch]
        if not closed:
            return
        for decision_id in closed:
            record = self._unknown.pop(decision_id)
            self.logger.warning(
                f"Decision {decision_id} from phase {record.get('phase')} (round {record.get('round')}) is still "
                f"{record.get('disposition')!r} after its phase closed; it no longer holds decisions"
            )
            self._emit_trace({**record, "unresolved_at_phase_close": True})
        if not self._unknown:
            self._unblock()

    def _block_on_unknown(self) -> None:
        if len(self._unknown) == 1:
            self.logger.warning("A disposition is unknown; no new decision until the disposition tracker reconciles it")
        if self.reconcile_request is not None and (self._reconcile_task is None or self._reconcile_task.done()):
            self._reconcile_task = asyncio.create_task(self._request_reconciliation())

    def _unblock(self) -> None:
        if self._reconcile_task is not None:
            if self._reconcile_task is not asyncio.current_task():
                self._reconcile_task.cancel()
            self._reconcile_task = None
        self.logger.info("No unknown disposition holds decisions any more; decisions resume")
        self._settled.set()

    async def _request_reconciliation(self) -> None:
        for _ in range(self.reconcile_retry_limit):
            if not self._blocked_on_unknown:
                return
            try:
                result = self.reconcile_request() if self.reconcile_request is not None else None
                if hasattr(result, "__await__"):
                    await result
            except Exception as exc:
                self.logger.warning(f"Reconciliation request failed: {exc}")
            await asyncio.sleep(self.reconcile_retry_interval)
        if self._blocked_on_unknown:
            self.logger.warning(
                f"Still waiting for the disposition tracker to reconcile after {self.reconcile_retry_limit} "
                "reconciliation requests"
            )

    async def _wait_until_settled(self) -> None:
        """Wait until no submission awaits a disposition and no unknown disposition blocks decisions."""
        while self._pending or self._blocked_on_unknown:
            self._settled.clear()
            await self._settled.wait()

    async def _notify(self, outcome: ActionOutcome) -> ActionOutcome:
        for listener in self._action_listeners:
            try:
                result = listener(outcome)
                if hasattr(result, "__await__"):
                    await result
            except Exception:
                self.logger.exception(
                    f"Action listener failed for the {outcome.status!r} action in phase {outcome.phase}"
                )
        return outcome

    async def _continuous_phase_loop(self, phase: PhaseId, epoch: int, entry: asyncio.Task | None = None) -> None:
        """Run repeated actions, after the phase-entry action, while the phase remains active."""
        try:
            if entry is not None:
                await asyncio.wait({entry})
            while self._continuous_phase_active(epoch):
                await asyncio.sleep(self.phase_engine.next_action_delay())
                if not self._continuous_phase_active(epoch):
                    break
                try:
                    await self._execute_phase_action(phase, epoch)
                except Exception:
                    self.logger.exception(f"Action in continuous phase {phase} failed; continuing")
        except asyncio.CancelledError:
            self.logger.debug(f"Continuous phase {phase} cancelled")

    def _current_round(self) -> Any:
        return getattr(getattr(self.state, "meta", None), "round", None)

    def _gated_occurrence(self, phase: PhaseId) -> PhaseOccurrence | None:
        occurrence = self._phase_occurrence
        if occurrence is None or occurrence.phase != phase or self.phase_engine.is_continuous(phase):
            return None
        return occurrence

    def _occurrence_decided(self, occurrence: PhaseOccurrence) -> bool:
        if occurrence == self._decided_occurrence:
            return True
        return self.decision_gate is not None and self.decision_gate.is_decided(occurrence)

    def _record_decided(self, occurrence: PhaseOccurrence | None, epoch: int, outcome: DecisionOutcome) -> None:
        if occurrence is None:
            return
        if epoch == self._phase_epoch:
            self._decided_occurrence = occurrence
        if self.decision_gate is None:
            return
        try:
            self.decision_gate.mark_decided(occurrence, outcome)
        except Exception:
            self.logger.exception(
                f"Decision gate failed to record the {outcome!r} decision for phase {occurrence.phase} "
                f"(round {occurrence.round})"
            )

    def _continuous_phase_active(self, epoch: int) -> bool:
        return self.in_continuous_phase and epoch == self._phase_epoch

    def _phase_busy(self) -> bool:
        entry_running = self._entry_task is not None and not self._entry_task.done()
        loop_running = self._continuous_task is not None and not self._continuous_task.done()
        return entry_running or loop_running or self._decision_lock.locked()

    def _cancel_phase_tasks(self) -> None:
        self.in_continuous_phase = False
        current = asyncio.current_task()
        for task in (self._continuous_task, self._entry_task):
            if task is not None and task is not current:
                task.cancel()
        self._continuous_task = None
        self._entry_task = None

    async def _handle_introduction(self, phase: PhaseId, state: GameState) -> dict[str, Any]:
        """Return the ready message for the standard introduction phase."""
        return ready_message()

    def _connection_epoch(self) -> Any:
        return getattr(self.transport, "connection_epoch", None)

    def _identity_from(self, event: Event) -> PlayerIdentity | None:
        """The identity ``event`` proves for this agent's connection, if any."""
        data = event.data or {}
        epoch = self._connection_epoch()
        if event.type == SNAPSHOT_EVENT and isinstance(data.get("playerNumber"), int):
            return PlayerIdentity(data["playerNumber"], data.get("role"), "snapshot", epoch)
        if event.type == PLAYER_JOINED_EVENT:
            first_on_connection = not self._player_joined_seen or (
                epoch is not None and epoch != self._joined_connection
            )
            self._player_joined_seen = True
            self._joined_connection = epoch
            if first_on_connection and isinstance(data.get("playerNumber"), int):
                return PlayerIdentity(data["playerNumber"], data.get("role") or None, "player-joined", epoch)
            return None
        if self.bound_identity is not None:
            return None
        recovery = self.auth_mechanism_kwargs.get("recovery") or (self.auth_mechanism_kwargs.get("payload") or {}).get(
            "recovery"
        )
        if not recovery:
            return None
        for player in data.get("players", []) or []:
            if isinstance(player, dict) and player.get("recovery") == recovery and player.get("playerNumber"):
                return PlayerIdentity(player["playerNumber"], player.get("role"), "recovery", epoch)
        return None

    def _resolve_player_number(self, event: Event) -> bool:
        """Record the identity ``event`` proves; False when it contradicts the configured seat."""
        identity = self._identity_from(event)
        if identity is None:
            return True
        previous = self.bound_identity
        self.bound_identity = identity
        if hasattr(self.transport, "bound_identity"):
            self.transport.bound_identity = identity
        if previous != identity:
            self.logger.info(f"Identity bound: {json_record(identity.as_record())}")

        meta = getattr(self.state, "meta", None)
        if meta is not None and hasattr(meta, "player_number") and not meta.player_number:
            meta.player_number = identity.player_number
        configured = self._configured_player_number
        role = self._configured_role
        if configured is not None and configured != identity.player_number:
            problem = f"player {identity.player_number}, configured as player {configured}"
        elif role is not None and identity.role and role != identity.role:
            problem = f"role {identity.role!r}, configured as {role!r}"
        else:
            return True
        self.identity_error = IdentityMismatchError(f"the server bound this agent to {problem} ({identity.source})")
        self.logger.error(
            "Identity mismatch: "
            + json_record(
                {
                    **identity.as_record(),
                    "record": "identity-mismatch",
                    "configured_player_number": configured,
                    "configured_role": role,
                }
            )
        )
        return False
