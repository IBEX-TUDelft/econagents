"""Agent runtime for one simulated player."""

import asyncio
import logging
from pathlib import Path
from typing import Any, Callable

from econagents.adapters.protocol import INTRODUCTION_PHASE, IbexMessageCodec, ready_message
from econagents.adapters.parsing import JsonResponseParser
from econagents.adapters.prompts import JinjaPromptRenderer
from econagents.adapters.state import EventFieldStateProjector
from econagents.adapters.transport import AuthenticationMechanism, JoinPayloadAuth, WebSocketTransport
from econagents.domain.role import Role
from econagents.domain.logging import LoggerMixin
from econagents.runtime.phase_engine import PhaseEngine
from econagents.domain.messages import Event, PhaseId
from econagents.domain.state.game import GameState
from econagents.ports.codec import MessageCodec, MessageDecodeError
from econagents.ports.state import StateProjectorPort
from econagents.ports.transport import TransportPort

PhaseHandler = Callable[[PhaseId, GameState], Any]
EventHandler = Callable[[Event], Any]


class Agent(LoggerMixin):
    """Run one agent against a game server."""

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
    ) -> None:
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
        self._phase_occurrence: tuple[PhaseId | None, Any] | None = None
        self._decision_lock = asyncio.Lock()
        self._decision_owner: asyncio.Task | None = None
        self._event_handlers: dict[str, list[EventHandler]] = {}
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

    def register_phase_handler(self, phase: PhaseId, handler: PhaseHandler) -> "Agent":
        """Register a handler for a phase."""
        self._phase_handlers[phase] = handler
        return self

    async def start(self) -> None:
        """Connect to the game server and process events until stopped."""
        self.role.logger = self.logger
        self.running = True
        await self.transport.start_listening()

    async def stop(self) -> None:
        """Stop the agent and transport."""
        self.running = False
        self._phase_epoch += 1
        self._cancel_phase_tasks()
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
        self._resolve_player_number(event)

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
        while that phase's continuous loop is running. A transition into a different occurrence cancels
        the previous one's pending decision and loop. Must not be awaited from inside a phase decision.
        """
        if self._decision_owner is not None and self._decision_owner is asyncio.current_task():
            raise RuntimeError("handle_phase_transition cannot be awaited from inside a phase decision")

        occurrence = (phase, self._current_round())
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

        self.current_phase = phase
        self._phase_occurrence = occurrence
        if phase is None:
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

    async def execute_phase_action(self, phase: PhaseId) -> None:
        """Execute one action for a phase.

        Decisions are single-flight per agent: this waits until no other decision is in flight, except
        when called from inside a phase handler or role decision, where it runs inline. The result is
        dropped instead of sent if the agent moves to another phase occurrence, or stops, while it is
        being decided. If the transport raises ``ConnectionError`` while sending, the action is logged at
        ERROR as not transmitted and is not retried.
        """
        await self._execute_phase_action(phase, self._phase_epoch)

    async def _execute_phase_action(self, phase: PhaseId, epoch: int) -> None:
        current = asyncio.current_task()
        if self._decision_owner is not None and self._decision_owner is current:
            await self._decide_and_send(phase, epoch)
            return
        async with self._decision_lock:
            self._decision_owner = current
            try:
                await self._decide_and_send(phase, epoch)
            finally:
                self._decision_owner = None

    async def _decide_and_send(self, phase: PhaseId, epoch: int) -> None:
        if epoch != self._phase_epoch:
            self.logger.debug(f"Skipping decision for phase {phase}: the phase ended before it started")
            return

        if phase in self._phase_handlers:
            payload = await self._phase_handlers[phase](phase, self.state)
        else:
            payload = await self.role.handle_phase(phase, self.state, self.prompts_dir)

        if not payload:
            return
        if epoch != self._phase_epoch:
            self.logger.warning(
                f"Dropping stale action decided in phase {phase}; the agent is now in phase {self.current_phase}"
            )
            return
        frame = self.message_codec.encode_action(payload)
        try:
            await self.transport.send(frame)
        except ConnectionError as exc:
            self.logger.error(f"Action decided in phase {phase} was not transmitted ({exc}): {frame}")

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

    def _resolve_player_number(self, event: Event) -> None:
        meta = getattr(self.state, "meta", None)
        if meta is None or not hasattr(meta, "player_number") or meta.player_number:
            return

        recovery = self.auth_mechanism_kwargs.get("recovery") or (self.auth_mechanism_kwargs.get("payload") or {}).get(
            "recovery"
        )
        if not recovery:
            return

        for player in event.data.get("players", []) or []:
            if player.get("recovery") == recovery:
                meta.player_number = player.get("playerNumber")
                break
