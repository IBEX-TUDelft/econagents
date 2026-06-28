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
        self.in_continuous_phase = False
        if self._continuous_task is not None:
            self._continuous_task.cancel()
            self._continuous_task = None
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
        """Move to a new phase and execute the appropriate action behavior."""
        if self.in_continuous_phase and phase != self.current_phase:
            self.in_continuous_phase = False
            if self._continuous_task is not None:
                self._continuous_task.cancel()
                self._continuous_task = None

        self.current_phase = phase
        if phase is None:
            return

        if self.phase_engine.is_continuous(phase):
            self.in_continuous_phase = True
            self._continuous_task = asyncio.create_task(self._continuous_phase_loop(phase))

        await self.execute_phase_action(phase)

    async def execute_phase_action(self, phase: PhaseId) -> None:
        """Execute one action for a phase."""
        if phase in self._phase_handlers:
            payload = await self._phase_handlers[phase](phase, self.state)
        else:
            payload = await self.role.handle_phase(phase, self.state, self.prompts_dir)

        if payload:
            await self.transport.send(self.message_codec.encode_action(payload))

    async def _continuous_phase_loop(self, phase: PhaseId) -> None:
        """Run repeated actions while the current phase remains active."""
        try:
            while self.in_continuous_phase:
                await asyncio.sleep(self.phase_engine.next_action_delay())
                if not self.in_continuous_phase or self.current_phase != phase:
                    break
                await self.execute_phase_action(phase)
        except asyncio.CancelledError:
            self.logger.debug(f"Continuous phase {phase} cancelled")

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
