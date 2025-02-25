import asyncio
import json
import logging
import random
from typing import Any, Callable, Optional

from econagents.core.agent import Agent
from econagents.core.events import Message
from econagents.core.manager.base import AgentManager
from econagents.core.state.game import GameState
from econagents.llm.openai import ChatOpenAI


class TurnBasedManager(AgentManager):
    """
    A generic manager for turn-based games that handles phase transitions.

    This manager provides a foundation for implementing turn-based game agents.
    """

    def __init__(
        self,
        url: str,
        login_payload: dict[str, Any],
        game_id: int,
        phase_transition_event: str,
        logger: logging.Logger,
        state: Optional[GameState] = None,
        agent: Optional[Agent] = None,
        llm: ChatOpenAI = ChatOpenAI(),
    ):
        """
        Initialize the TurnWithStateManager.

        Args:
            url: WebSocket server URL
            login_payload: Authentication payload for the WebSocket
            phase_transition_event: Event name for phase transitions
            game_id: Identifier for the current game
            logger: Logger instance for tracking events
            state: Optional game state object to track game state
            agent: Optional agent instance to handle game phases
        """
        super().__init__(url, login_payload, game_id, logger, llm)
        self.game_id = game_id
        self._agent = agent
        self.state = state
        self.current_phase = None
        self.phase_transition_event = phase_transition_event

        # Register the phase transition handler
        self.register_event_handler(self.phase_transition_event, self._handle_phase_transition)

        # Set up global pre-event hook for state updates if state is provided
        if self.state:
            self.register_global_pre_event_hook(self._update_state)

    @property
    def agent(self) -> Optional[Agent]:
        """Get the current agent instance."""
        return self._agent

    @agent.setter
    def agent(self, agent: Agent):
        """Set the agent instance."""
        self._agent = agent

    async def _update_state(self, message: Message):
        """Update the game state when an event is received."""
        if self.state:
            self.state.update(message)
            self.logger.debug(f"Updated state: {self.state}")

    async def _handle_phase_transition(self, message: Message, event_key: str = "phase"):
        """Handle phase transition events."""
        new_phase = message.data.get(event_key)
        self.logger.info(f"Transitioning to phase {new_phase}")

        self.current_phase = new_phase

        if new_phase is not None:
            await self._handle_phase(new_phase)

    async def _handle_phase(self, phase: int):
        """
        Handle phase transitions by delegating to the agent.

        Subclasses can override this method to implement custom phase handling.
        The default implementation delegates to the agent if one exists.
        """
        if not self.agent:
            self.logger.warning("No agent set, cannot handle phase")
            return

        payload = await self.agent.handle_phase(phase, self.state)
        if payload:
            await self.send_message(json.dumps(payload))
            self.logger.info(f"Phase {phase}, sent payload: {payload}")

    def register_phase_handler(self, phase: int, handler: Callable[[int, Any], Any]):
        """
        Register a custom handler for a specific game phase.

        Args:
            phase: The phase number to handle
            handler: A function that takes the phase number and state, and returns a payload
        """

        # This method provides a convenient API for registering custom phase handlers
        async def phase_handler(message: Message):
            if message.data.get("phase") == phase:
                payload = handler(phase, self.state)
                if hasattr(payload, "__await__"):
                    payload = await payload
                if payload:
                    await self.send_message(json.dumps(payload))

        self.register_event_handler(self.phase_transition_event, phase_handler)
        return self


class TurnBasedWithContinuousManager(TurnBasedManager):
    """
    A manager for games that combine turn-based and continuous action phases.

    This manager extends TurnBasedManager by adding support for continuous phases
    where the agent will regularly take actions at configurable intervals.
    """

    def __init__(
        self,
        url: str,
        login_payload: dict[str, Any],
        game_id: int,
        phase_transition_event: str,
        logger: logging.Logger,
        continuous_phases: set[int],
        min_action_delay: int = 10,
        max_action_delay: int = 20,
        state: Optional[GameState] = None,
        agent: Optional[Agent] = None,
        llm: ChatOpenAI = ChatOpenAI(),
    ):
        """
        Initialize the TurnAndContinuousPhases manager.

        Args:
            url: WebSocket server URL
            login_payload: Authentication payload for the WebSocket
            game_id: Identifier for the current game
            phase_transition_event: Event name for phase transitions
            logger: Logger instance for tracking events
            continuous_phases: Set of phase numbers that should be treated as continuous
            min_action_delay: Minimum delay in seconds between actions in continuous phases
            max_action_delay: Maximum delay in seconds between actions in continuous phases
            llm: LLM instance to use for the agent
            state: Optional game state object to track game state
            agent: Optional agent instance to handle game phases
        """
        super().__init__(
            url=url,
            login_payload=login_payload,
            game_id=game_id,
            phase_transition_event=phase_transition_event,
            logger=logger,
            state=state,
            agent=agent,
            llm=llm,
        )
        self.continuous_phases = continuous_phases
        self.min_action_delay = min_action_delay
        self.max_action_delay = max_action_delay
        self.in_continuous_phase = False
        self.continuous_phase_task: Optional[asyncio.Task] = None

    async def _handle_phase_transition(self, message: Message, event_key: str = "phase"):
        """
        Handle phase transition events, with special handling for continuous phases.

        When transitioning to a continuous phase, starts a background task to regularly
        prompt the agent for actions. When leaving a continuous phase, cancels that task.
        """
        new_phase = message.data.get(event_key)
        self.logger.info(f"Transitioning to phase {new_phase}")

        if self.in_continuous_phase and new_phase != self.current_phase:
            self.logger.info(f"Stopping continuous phase {self.current_phase}")
            self.in_continuous_phase = False
            if self.continuous_phase_task:
                self.continuous_phase_task.cancel()
                self.continuous_phase_task = None

        self.current_phase = new_phase

        if new_phase is not None:
            await self._handle_phase(new_phase)

    async def _handle_phase(self, phase: int):
        """
        Handle phase transitions with special handling for continuous phases.

        For continuous phases, starts a background task that regularly prompts the
        agent for actions. For turn-based phases, delegates to the parent class.
        """
        if not self.agent:
            self.logger.warning("No agent set, cannot handle phase")
            return

        if phase in self.continuous_phases:
            self.logger.info(f"Entering continuous phase {phase}")
            self.in_continuous_phase = True

            # Cancel existing task if there is one
            if self.continuous_phase_task and not self.continuous_phase_task.done():
                self.continuous_phase_task.cancel()

            # Start a new continuous phase task
            self.continuous_phase_task = asyncio.create_task(self._continuous_phase_loop(phase))

            # Also send an initial action
            payload = await self.agent.handle_phase(phase, self.state)
            if payload:
                await self.send_message(json.dumps(payload))
                self.logger.info(f"Phase {phase} (continuous), sent initial payload: {payload}")
        else:
            # For non-continuous phases, use the parent class implementation
            await super()._handle_phase(phase)

    async def _continuous_phase_loop(self, phase: int):
        """
        Run a loop while in a continuous phase, regularly prompting the agent for actions.

        Args:
            phase: The phase number of the continuous phase
        """
        if not self.agent:
            return

        try:
            while self.in_continuous_phase:
                delay = random.randint(self.min_action_delay, self.max_action_delay)
                self.logger.debug(f"Waiting {delay} seconds before next action in phase {phase}")
                await asyncio.sleep(delay)

                if not self.in_continuous_phase or self.current_phase != phase:
                    break

                payload = await self.agent.handle_phase(phase, self.state)
                if payload:
                    await self.send_message(json.dumps(payload))
                    self.logger.debug(f"Phase {phase} (continuous), sent payload: {payload}")
        except asyncio.CancelledError:
            self.logger.info(f"Continuous phase {phase} loop cancelled")
        except Exception as e:
            self.logger.exception(f"Error in continuous phase {phase} loop: {e}")

    async def stop(self):
        """Stop the manager and cancel any continuous phase tasks."""
        self.in_continuous_phase = False
        if self.continuous_phase_task:
            self.continuous_phase_task.cancel()
            self.continuous_phase_task = None
        await super().stop()
