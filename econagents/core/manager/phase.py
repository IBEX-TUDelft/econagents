import asyncio
import json
import logging
import random
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, Optional

from econagents.core.agent_role import AgentRole
from econagents.core.events import Message
from econagents.core.manager.base import AgentManager
from econagents.core.state.game import GameState
from econagents.core.transport import AuthenticationMechanism


class PhaseManager(AgentManager, ABC):
    """
    Abstract manager that handles the concept of 'phases' in a game.

    This manager standardizes the interface for phase-based games with optional
    continuous-time phase handling.

    Features:
    1. Standardized interface for starting a phase

    2. Optional continuous "tick loop" for phases

    All configuration parameters can be:

    1. Provided at initialization time

    2. Injected later using property setters

    Args:
        url (Optional[str]): WebSocket server URL
        phase_transition_event (Optional[str]): Event name for phase transitions
        phase_identifier_key (Optional[str]): Key in the event data that identifies the phase
        continuous_phases (Optional[set[int]]): set of phase numbers that should be treated as continuous
        min_action_delay (Optional[int]): Minimum delay in seconds between actions in continuous-time phases
        max_action_delay (Optional[int]): Maximum delay in seconds between actions in continuous-time phases
        state (Optional[GameState]): Game state object to track game state
        agent_role (Optional[AgentRole]): Agent role instance to handle game phases
        auth_mechanism (Optional[AuthenticationMechanism]): Authentication mechanism to use
        auth_mechanism_kwargs (Optional[dict[str, Any]]): Keyword arguments for the authentication mechanism
        logger (Optional[logging.Logger]): Logger instance for tracking events
        prompts_dir (Optional[Path]): Directory containing the prompt templates
    """

    def __init__(
        self,
        url: Optional[str] = None,
        phase_transition_event: Optional[str] = None,
        phase_identifier_key: Optional[str] = None,
        continuous_phases: Optional[set[int]] = None,
        min_action_delay: Optional[int] = None,
        max_action_delay: Optional[int] = None,
        state: Optional[GameState] = None,
        agent_role: Optional[AgentRole] = None,
        auth_mechanism: Optional[AuthenticationMechanism] = None,
        auth_mechanism_kwargs: Optional[dict[str, Any]] = None,
        logger: Optional[logging.Logger] = None,
        prompts_dir: Optional[Path] = None,
    ):
        super().__init__(
            url=url,
            logger=logger,
            auth_mechanism=auth_mechanism,
            auth_mechanism_kwargs=auth_mechanism_kwargs,
        )
        self._agent_role = agent_role
        self._state = state
        self.current_phase: Optional[int] = None
        self._phase_transition_event = phase_transition_event
        self._phase_identifier_key = phase_identifier_key
        self._continuous_phases = continuous_phases
        self._min_action_delay = min_action_delay
        self._max_action_delay = max_action_delay
        self._prompts_dir = prompts_dir
        self._continuous_task: Optional[asyncio.Task] = None
        self.in_continuous_phase = False

        # Register the phase transition handler if we have an event name
        if self._phase_transition_event:
            self.register_event_handler(self._phase_transition_event, self._on_phase_transition_event)

        # set up global pre-event hook for state updates if state is provided
        if self._state:
            self.register_global_pre_event_hook(self._update_state)

    @property
    def agent_role(self) -> Optional[AgentRole]:
        """Get the current agent role instance."""
        return self._agent_role

    @agent_role.setter
    def agent_role(self, value: AgentRole):
        """Set the agent role instance."""
        self._agent_role = value
        if self._agent_role:
            self._agent_role.logger = self.logger

    @property
    def state(self) -> GameState:
        """Get the current game state."""
        return self._state  # type: ignore

    @state.setter
    def state(self, value: Optional[GameState]):
        """Set the game state."""
        old_state = self._state
        self._state = value

        # If we didn't have a state before but now we do, set up the state update hook
        if not old_state and self._state:
            self.register_global_pre_event_hook(self._update_state)

    @property
    def phase_transition_event(self) -> str:
        """Get the phase transition event name."""
        return self._phase_transition_event  # type: ignore

    @phase_transition_event.setter
    def phase_transition_event(self, value: str):
        """Set the phase transition event name."""
        old_event = self._phase_transition_event
        self._phase_transition_event = value

        # Update the event handler if the event name changed
        if old_event != self._phase_transition_event:
            if old_event:
                self.unregister_event_handler(old_event)
            self.register_event_handler(self._phase_transition_event, self._on_phase_transition_event)

    @property
    def phase_identifier_key(self) -> str:
        """Get the phase identifier key."""
        return self._phase_identifier_key  # type: ignore

    @phase_identifier_key.setter
    def phase_identifier_key(self, value: str):
        """Set the phase identifier key."""
        self._phase_identifier_key = value

    @property
    def continuous_phases(self) -> set[int]:
        """Get the set of continuous-time phases."""
        return self._continuous_phases  # type: ignore

    @continuous_phases.setter
    def continuous_phases(self, value: set[int]):
        """Set the continuous-time phases."""
        self._continuous_phases = value

    @property
    def min_action_delay(self) -> int:
        """Get the minimum action delay."""
        return self._min_action_delay  # type: ignore

    @min_action_delay.setter
    def min_action_delay(self, value: int):
        """Set the minimum action delay."""
        self._min_action_delay = value

    @property
    def max_action_delay(self) -> int:
        """Get the maximum action delay."""
        return self._max_action_delay  # type: ignore

    @max_action_delay.setter
    def max_action_delay(self, value: int):
        """Set the maximum action delay."""
        self._max_action_delay = value

    @property
    def prompts_dir(self) -> Path:
        """Get the prompts directory."""
        return self._prompts_dir  # type: ignore

    @prompts_dir.setter
    def prompts_dir(self, value: Path):
        """Set the prompts directory."""
        self._prompts_dir = value

    @property
    def llm_provider(self):
        """Get the LLM provider from the agent role."""
        if self._agent_role and hasattr(self._agent_role, "llm"):
            return self._agent_role.llm
        return None

    async def start(self):
        """Start the manager."""
        # TODO: is there a better place to do this?
        if self._agent_role:
            self._agent_role.logger = self.logger
        await super().start()

    async def _update_state(self, message: Message):
        """Update the game state when an event is received.

        Args:
            message (Message): The message containing the event data
        """
        if self._state:
            self._state.update(message)
            self.logger.debug(f"Updated state: {self._state}")

    async def _on_phase_transition_event(self, message: Message):
        """
        Process a phase transition event.

        Extracts the new phase from the message and calls handle_phase_transition.

        Args:
            message (Message): The message containing the event data
        """
        if not self.phase_identifier_key:
            raise ValueError("Phase identifier key is not set")

        new_phase = message.data.get(self.phase_identifier_key)
        await self.handle_phase_transition(new_phase)

    async def handle_phase_transition(self, new_phase: Optional[int]):
        """
        Handle a phase transition.

        This method is the main orchestrator for phase transitions:
        1. If leaving a continuous-time phase, stops the continuous task
        2. Updates the current phase
        3. Starts a continuous task if entering a continuous-time phase
        4. Executes a single action if entering a non-continuous-time phase

        Args:
            new_phase (Optional[int]): The new phase number
        """
        self.logger.info(f"Transitioning to phase {new_phase}")

        # If we were in a continuous-time phase, stop it
        if self.in_continuous_phase and new_phase != self.current_phase:
            self.logger.info(f"Stopping continuous-time phase {self.current_phase}")
            self.in_continuous_phase = False
            if self._continuous_task:
                self._continuous_task.cancel()
                self._continuous_task = None

        self.current_phase = new_phase

        if new_phase is not None:
            # If the new phase is continuous, start a continuous task
            if self.continuous_phases and new_phase in self.continuous_phases:
                self.in_continuous_phase = True
                self._continuous_task = asyncio.create_task(self._continuous_phase_loop(new_phase))

                # Execute an initial action
                await self.execute_phase_action(new_phase)
            else:
                # Execute a single action for non-continuous-time phases
                await self.execute_phase_action(new_phase)

    async def _continuous_phase_loop(self, phase: int):
        """
        Run a loop that periodically executes actions for a continuous-time phase.

        Args:
            phase (int): The phase number
        """
        try:
            while self.in_continuous_phase:
                # Wait for a random delay before executing the next action
                delay = random.randint(self.min_action_delay, self.max_action_delay)
                self.logger.debug(f"Waiting {delay} seconds before next action in phase {phase}")
                await asyncio.sleep(delay)

                # Check if we're still in the same continuous-time phase
                if not self.in_continuous_phase or self.current_phase != phase:
                    break

                # Execute the action
                await self.execute_phase_action(phase)
        except asyncio.CancelledError:
            self.logger.info(f"Continuous-time phase {phase} loop cancelled")
        except Exception as e:
            self.logger.exception(f"Error in continuous-time phase {phase} loop: {e}")

    @abstractmethod
    async def execute_phase_action(self, phase: int):
        """
        Execute one action for the current phase.

        This is the core method that subclasses must implement to define
        how to handle actions for a specific phase.

        Args:
            phase (int): The phase number
        """
        pass

    async def stop(self):
        """Stop the manager and cancel any continuous-time phase tasks."""
        self.in_continuous_phase = False
        if self._continuous_task:
            self._continuous_task.cancel()
            self._continuous_task = None
        await super().stop()


class TurnBasedPhaseManager(PhaseManager):
    """
    A manager for turn-based games that handles phase transitions.

    This manager inherits from PhaseManager and provides a concrete implementation
    for executing actions in each phase. All phases are treated as turn-based,
    meaning actions are only taken when explicitly triggered (no continuous actions).

    Args:
        url (Optional[str]): WebSocket server URL
        phase_transition_event (Optional[str]): Event name for phase transitions
        phase_identifier_key (Optional[str]): Key in the event data that identifies the phase
        auth_mechanism (Optional[AuthenticationMechanism]): Authentication mechanism to use
        auth_mechanism_kwargs (Optional[dict[str, Any]]): Keyword arguments for the authentication mechanism
        state (Optional[GameState]): Game state object to track game state
        agent_role (Optional[AgentRole]): Agent role instance to handle game phases
        logger (Optional[logging.Logger]): Logger instance for tracking events
        prompts_dir (Optional[Path]): Directory containing the prompt templates
    """

    def __init__(
        self,
        url: Optional[str] = None,
        phase_transition_event: Optional[str] = None,
        phase_identifier_key: Optional[str] = None,
        auth_mechanism: Optional[AuthenticationMechanism] = None,
        auth_mechanism_kwargs: Optional[dict[str, Any]] = None,
        state: Optional[GameState] = None,
        agent_role: Optional[AgentRole] = None,
        logger: Optional[logging.Logger] = None,
        prompts_dir: Optional[Path] = None,
    ):
        super().__init__(
            url=url,
            phase_transition_event=phase_transition_event,
            phase_identifier_key=phase_identifier_key,
            auth_mechanism=auth_mechanism,
            auth_mechanism_kwargs=auth_mechanism_kwargs,
            continuous_phases=set(),
            state=state,
            agent_role=agent_role,
            logger=logger,
            prompts_dir=prompts_dir,
        )
        # Register phase handlers
        self._phase_handlers: dict[int, Callable[[int, Any], Any]] = {}

    async def execute_phase_action(self, phase: int):
        """
        Execute an action for the given phase by delegating to the registered handler or agent.

        Args:
            phase (int): The phase number
        """
        payload = None

        if phase in self._phase_handlers:
            # If we have a registered handler for this phase, use it
            self.logger.debug(f"Using registered handler for phase {phase}")
            payload = await self._phase_handlers[phase](phase, self.state)
        elif self.agent_role:
            # If we don't have a registered handler but we have an agent, use the agent
            self.logger.debug(f"Using agent {self.agent_role.name} handle_phase for phase {phase}")
            payload = await self.agent_role.handle_phase(phase, self.state, self.prompts_dir)

        if payload:
            await self.send_message(json.dumps(payload))

    def register_phase_handler(self, phase: int, handler: Callable[[int, Any], Any]):
        """
        Register a custom handler for a specific phase.

        Args:
            phase (int): The phase number
            handler (Callable[[int, Any], Any]): The function to call when this phase is active
        """
        self._phase_handlers[phase] = handler
        self.logger.debug(f"Registered handler for phase {phase}")


class HybridPhaseManager(PhaseManager):
    """
    A manager for games that combine turn-based and continuous action phases.

    This manager extends PhaseManager and configures it with specific phases
    that should be treated as continuous. By default, all phases are treated as
    turn-based unless explicitly included in the continuous_phases parameter.

    For continuous-time phases, the manager will automatically execute actions periodically
    with random delays between min_action_delay and max_action_delay seconds.

    Args:
        continuous_phases (Optional[set[int]]): Set of phase numbers that should be treated as continuous
        url (Optional[str]): WebSocket server URL
        auth_mechanism (Optional[AuthenticationMechanism]): Authentication mechanism to use
        auth_mechanism_kwargs (Optional[dict[str, Any]]): Keyword arguments for the authentication mechanism
        phase_transition_event (Optional[str]): Event name for phase transitions
        phase_identifier_key (Optional[str]): Key in the event data that identifies the phase
        min_action_delay (Optional[int]): Minimum delay in seconds between actions in continuous-time phases
        max_action_delay (Optional[int]): Maximum delay in seconds between actions in continuous-time phases
        state (Optional[GameState]): Game state object to track game state
        agent_role (Optional[AgentRole]): Agent role instance to handle game phases
        logger (Optional[logging.Logger]): Logger instance for tracking events
        prompts_dir (Optional[Path]): Directory containing the prompt templates
    """

    def __init__(
        self,
        continuous_phases: Optional[set[int]] = None,
        url: Optional[str] = None,
        auth_mechanism: Optional[AuthenticationMechanism] = None,
        auth_mechanism_kwargs: Optional[dict[str, Any]] = None,
        phase_transition_event: Optional[str] = None,
        phase_identifier_key: Optional[str] = None,
        min_action_delay: Optional[int] = None,
        max_action_delay: Optional[int] = None,
        state: Optional[GameState] = None,
        agent_role: Optional[AgentRole] = None,
        logger: Optional[logging.Logger] = None,
        prompts_dir: Optional[Path] = None,
    ):
        super().__init__(
            url=url,
            phase_transition_event=phase_transition_event,
            phase_identifier_key=phase_identifier_key,
            auth_mechanism=auth_mechanism,
            auth_mechanism_kwargs=auth_mechanism_kwargs,
            continuous_phases=continuous_phases,
            min_action_delay=min_action_delay,
            max_action_delay=max_action_delay,
            state=state,
            agent_role=agent_role,
            logger=logger,
            prompts_dir=prompts_dir,
        )
        # Register phase handlers
        self._phase_handlers: dict[int, Callable[[int, Any], Any]] = {}

    async def execute_phase_action(self, phase: int):
        """
        Execute an action for the given phase by delegating to the registered handler or agent.

        Args:
            phase (int): The phase number
        """
        payload = None

        if phase in self._phase_handlers:
            # If we have a registered handler for this phase, use it
            self.logger.debug(f"Using registered handler for phase {phase}")
            payload = await self._phase_handlers[phase](phase, self.state)
        elif self.agent_role:
            # If we don't have a registered handler but we have an agent, use the agent
            self.logger.debug(f"Using agent {self.agent_role.name} handle_phase for phase {phase}")
            payload = await self.agent_role.handle_phase(phase, self.state, self.prompts_dir)

        if payload:
            await self.send_message(json.dumps(payload))

    def register_phase_handler(self, phase: int, handler: Callable[[int, Any], Any]):
        """
        Register a custom handler for a specific phase.

        Args:
            phase (int): The phase number
            handler (Callable[[int, Any], Any]): The function to call when this phase is active
        """
        self._phase_handlers[phase] = handler
        self.logger.debug(f"Registered handler for phase {phase}")
