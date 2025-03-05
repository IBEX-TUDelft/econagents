import asyncio
import json
import logging
import random
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

from econagents.core.agent import Agent
from econagents.core.events import Message
from econagents.core.manager.base import AgentManager
from econagents.core.state.game import GameState
from econagents.core.transport import AuthenticationMechanism, SimpleLoginPayloadAuth


class PhaseManager(AgentManager, ABC):
    """
    Abstract manager that handles the concept of 'phases' in a game.

    This manager standardizes the interface for phase-based games with hooks for
    phase transitions and optional continuous phase handling.

    Features:
    1. Standardized interface for starting a phase
    2. Optional continuous "tick loop" for phases
    3. Hooks for "on phase start," "on phase end," and "on phase transition event"
    """

    def __init__(
        self,
        url: str,
        game_id: int,
        logger: logging.Logger,
        phase_transition_event: str = "phase-transition",
        phase_identifier_key: str = "phase",
        continuous_phases: Optional[set[int]] = None,
        min_action_delay: int = 10,
        max_action_delay: int = 20,
        auth_mechanism: Optional[AuthenticationMechanism] = SimpleLoginPayloadAuth(),
        auth_mechanism_kwargs: Optional[dict[str, Any]] = None,
        state: Optional[GameState] = None,
        agent: Optional[Agent] = None,
    ):
        """
        Initialize the PhaseManager.

        Args:
            url: WebSocket server URL
            game_id: Identifier for the current game
            logger: Logger instance for tracking events
            phase_transition_event: Event name for phase transitions
            phase_identifier_key: Key in the event data that identifies the phase
            continuous_phases: set of phase numbers that should be treated as continuous
            min_action_delay: Minimum delay in seconds between actions in continuous phases
            max_action_delay: Maximum delay in seconds between actions in continuous phases
            auth_mechanism: Authentication mechanism to use
            auth_mechanism_kwargs: Keyword arguments for the authentication mechanism
            state: Optional game state object to track game state
            agent: Optional agent instance to handle game phases
        """
        super().__init__(
            url=url,
            game_id=game_id,
            logger=logger,
            auth_mechanism=auth_mechanism,
            auth_mechanism_kwargs=auth_mechanism_kwargs,
        )
        self._agent = agent
        self.state = state
        self.current_phase: Optional[int] = None
        self.phase_transition_event = phase_transition_event
        self.phase_identifier_key = phase_identifier_key
        self.continuous_phases = continuous_phases or set()
        self.min_action_delay = min_action_delay
        self.max_action_delay = max_action_delay
        self._continuous_task: Optional[asyncio.Task] = None
        self.in_continuous_phase = False

        # Register the phase transition handler
        self.register_event_handler(self.phase_transition_event, self._on_phase_transition_event)

        # set up global pre-event hook for state updates if state is provided
        if self.state:
            self.register_global_pre_event_hook(self._update_state)

    @property
    def agent(self) -> Optional[Agent]:
        """Get the current agent instance."""
        return self._agent

    @agent.setter
    def agent(self, agent: Agent):
        """set the agent instance."""
        self._agent = agent

    async def _update_state(self, message: Message):
        """Update the game state when an event is received."""
        if self.state:
            self.state.update(message)
            self.logger.debug(f"Updated state: {self.state}")

    async def _on_phase_transition_event(self, message: Message):
        """
        Process a phase transition event.

        Extracts the new phase from the message and calls handle_phase_transition.
        """
        new_phase = message.data.get(self.phase_identifier_key)
        await self.handle_phase_transition(new_phase)

    async def handle_phase_transition(self, new_phase: Optional[int]):
        """
        Handle a phase transition.

        This method is the main orchestrator for phase transitions:
        1. If leaving a continuous phase, stops the continuous task
        2. Calls the on_phase_end hook for the old phase
        3. Updates the current phase
        4. Calls the on_phase_start hook for the new phase
        5. Starts a continuous task if entering a continuous phase
        6. Executes a single action if entering a non-continuous phase

        Args:
            new_phase: The new phase number
        """
        self.logger.info(f"Transitioning to phase {new_phase}")

        # If we were in a continuous phase, stop it
        if self.in_continuous_phase and new_phase != self.current_phase:
            self.logger.info(f"Stopping continuous phase {self.current_phase}")
            self.in_continuous_phase = False
            if self._continuous_task:
                self._continuous_task.cancel()
                self._continuous_task = None

        # Call the on_phase_end hook for the old phase
        old_phase = self.current_phase
        if old_phase is not None:
            await self.on_phase_end(old_phase)

        # Update current phase
        self.current_phase = new_phase

        if new_phase is not None:
            # Call the on_phase_start hook for the new phase
            await self.on_phase_start(new_phase)

            # If the new phase is continuous, start a continuous task
            if new_phase in self.continuous_phases:
                self.in_continuous_phase = True
                self._continuous_task = asyncio.create_task(self._continuous_phase_loop(new_phase))

                # Execute an initial action
                await self.execute_phase_action(new_phase)
            else:
                # Execute a single action for non-continuous phases
                await self.execute_phase_action(new_phase)

    async def _continuous_phase_loop(self, phase: int):
        """
        Run a loop that periodically executes actions for a continuous phase.

        Args:
            phase: The phase number
        """
        try:
            while self.in_continuous_phase:
                # Wait for a random delay before executing the next action
                delay = random.randint(self.min_action_delay, self.max_action_delay)
                self.logger.debug(f"Waiting {delay} seconds before next action in phase {phase}")
                await asyncio.sleep(delay)

                # Check if we're still in the same continuous phase
                if not self.in_continuous_phase or self.current_phase != phase:
                    break

                # Execute the action
                await self.execute_phase_action(phase)
        except asyncio.CancelledError:
            self.logger.info(f"Continuous phase {phase} loop cancelled")
        except Exception as e:
            self.logger.exception(f"Error in continuous phase {phase} loop: {e}")

    @abstractmethod
    async def execute_phase_action(self, phase: int):
        """
        Execute one action for the current phase.

        This is the core method that subclasses must implement to define
        how to handle actions for a specific phase.

        Args:
            phase: The phase number
        """
        pass

    async def on_phase_start(self, phase: int):
        """
        Hook that is called when a phase starts.

        Subclasses can override this to implement custom behavior.

        Args:
            phase: The phase number
        """
        pass

    async def on_phase_end(self, phase: int):
        """
        Hook that is called when a phase ends.

        Subclasses can override this to implement custom behavior.

        Args:
            phase: The phase number
        """
        pass

    async def stop(self):
        """Stop the manager and cancel any continuous phase tasks."""
        self.in_continuous_phase = False
        if self._continuous_task:
            self._continuous_task.cancel()
            self._continuous_task = None
        await super().stop()


class DiscretePhaseManager(PhaseManager):
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
        self._phase_handlers: dict[int, Callable[[int, Any], Any]] = {}

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


class HybridPhaseManager(PhaseManager):
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
        continuous_phases: set[int],
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
            continuous_phases: set of phase numbers that should be treated as continuous
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
        self._phase_handlers: dict[int, Callable[[int, Any], Any]] = {}

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
