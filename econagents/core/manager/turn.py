import json
import logging
from typing import Any, Callable, Dict, Optional, Set

from econagents.core.agent import Agent
from econagents.core.manager.phase import PhaseManager
from econagents.core.state.game import GameState
from econagents.core.transport import AuthenticationMechanism, SimpleLoginPayloadAuth


class TurnBasedManager(PhaseManager):
    """
    A manager for turn-based games that handles phase transitions.

    This manager inherits from PhaseManager and provides a concrete implementation
    for executing actions in each phase.
    """

    def __init__(
        self,
        url: str,
        game_id: int,
        logger: logging.Logger,
        phase_transition_event: str = "phase-transition",
        phase_identifier_key: str = "phase",
        auth_mechanism: Optional[AuthenticationMechanism] = SimpleLoginPayloadAuth(),
        auth_mechanism_kwargs: Optional[dict[str, Any]] = None,
        state: Optional[GameState] = None,
        agent: Optional[Agent] = None,
    ):
        """
        Initialize the TurnBasedManager.

        Args:
            url: WebSocket server URL
            game_id: Identifier for the current game
            logger: Logger instance for tracking events
            phase_transition_event: Event name for phase transitions
            phase_identifier_key: Key in the event data that identifies the phase
            auth_mechanism: Authentication mechanism to use
            auth_mechanism_kwargs: Keyword arguments for the authentication mechanism
            state: Optional game state object to track game state
            agent: Optional agent instance to handle game phases
        """
        super().__init__(
            url=url,
            game_id=game_id,
            logger=logger,
            phase_transition_event=phase_transition_event,
            phase_identifier_key=phase_identifier_key,
            auth_mechanism=auth_mechanism,
            auth_mechanism_kwargs=auth_mechanism_kwargs,
            continuous_phases=set(),  # No continuous phases
            state=state,
            agent=agent,
        )
        # Register phase handlers
        self._phase_handlers: Dict[int, Callable[[int, Any], Any]] = {}

    async def execute_phase_action(self, phase: int):
        """
        Execute an action for the given phase by delegating to the agent.

        Args:
            phase: The phase number
        """
        if not self.agent:
            self.logger.warning("No agent set, cannot handle phase")
            return

        # Check if there's a specific handler for this phase
        if phase in self._phase_handlers:
            handler = self._phase_handlers[phase]
            payload = await handler(phase, self.state)
        else:
            # Otherwise, use the agent's handle_phase method
            payload = await self.agent.handle_phase(phase, self.state)

        if payload:
            await self.send_message(json.dumps(payload))
            self.logger.info(f"Phase {phase}, sent payload: {payload}")

    def register_phase_handler(self, phase: int, handler: Callable[[int, Any], Any]):
        """
        Register a custom handler for a specific phase.

        Args:
            phase: The phase number
            handler: The function to call when this phase is active
        """
        self._phase_handlers[phase] = handler
        self.logger.debug(f"Registered handler for phase {phase}")


class TurnBasedWithContinuousManager(PhaseManager):
    """
    A manager for games that combine turn-based and continuous action phases.

    This manager extends PhaseManager and configures it with specific phases
    that should be treated as continuous.
    """

    def __init__(
        self,
        url: str,
        game_id: int,
        logger: logging.Logger,
        continuous_phases: Set[int],
        auth_mechanism: Optional[AuthenticationMechanism] = SimpleLoginPayloadAuth(),
        auth_mechanism_kwargs: Optional[dict[str, Any]] = None,
        phase_transition_event: str = "phase-transition",
        phase_identifier_key: str = "phase",
        min_action_delay: int = 10,
        max_action_delay: int = 20,
        state: Optional[GameState] = None,
        agent: Optional[Agent] = None,
    ):
        """
        Initialize the TurnBasedWithContinuousManager.

        Args:
            url: WebSocket server URL
            game_id: Identifier for the current game
            logger: Logger instance for tracking events
            continuous_phases: Set of phase numbers that should be treated as continuous
            auth_mechanism: Authentication mechanism to use
            auth_mechanism_kwargs: Keyword arguments for the authentication mechanism
            phase_transition_event: Event name for phase transitions
            phase_identifier_key: Key in the event data that identifies the phase
            min_action_delay: Minimum delay in seconds between actions in continuous phases
            max_action_delay: Maximum delay in seconds between actions in continuous phases
            state: Optional game state object to track game state
            agent: Optional agent instance to handle game phases
        """
        super().__init__(
            url=url,
            game_id=game_id,
            logger=logger,
            phase_transition_event=phase_transition_event,
            phase_identifier_key=phase_identifier_key,
            auth_mechanism=auth_mechanism,
            auth_mechanism_kwargs=auth_mechanism_kwargs,
            continuous_phases=continuous_phases,
            min_action_delay=min_action_delay,
            max_action_delay=max_action_delay,
            state=state,
            agent=agent,
        )
        # Register phase handlers
        self._phase_handlers: Dict[int, Callable[[int, Any], Any]] = {}

    async def execute_phase_action(self, phase: int):
        """
        Execute an action for the given phase by delegating to the agent.

        Args:
            phase: The phase number
        """
        if not self.agent:
            self.logger.warning("No agent set, cannot handle phase")
            return

        # Check if there's a specific handler for this phase
        if phase in self._phase_handlers:
            handler = self._phase_handlers[phase]
            payload = await handler(phase, self.state)
        else:
            # Otherwise, use the agent's handle_phase method
            payload = await self.agent.handle_phase(phase, self.state)

        if payload:
            await self.send_message(json.dumps(payload))
            log_method = self.logger.debug if self.in_continuous_phase else self.logger.info
            log_method(f"Phase {phase}{' (continuous)' if self.in_continuous_phase else ''}, sent payload: {payload}")

    def register_phase_handler(self, phase: int, handler: Callable[[int, Any], Any]):
        """
        Register a custom handler for a specific phase.

        Args:
            phase: The phase number
            handler: The function to call when this phase is active
        """
        self._phase_handlers[phase] = handler
        self.logger.debug(f"Registered handler for phase {phase}")
