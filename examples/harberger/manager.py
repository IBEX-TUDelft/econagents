import asyncio
import json
import logging
import random
from typing import Any, Optional, Dict, Callable

from econagents import Agent, AgentManager, Message
from econagents.llm.openai import ChatOpenAI
from examples.harberger.agents import Developer, Owner, Speculator
from examples.harberger.config import PATH_PROMPTS, game_mappings
from examples.harberger.state import HarbergerGameState


class HarbergerAgentManager(AgentManager):
    name: Optional[str] = None
    role: Optional[str] = None

    def __init__(self, url: str, login_payload: dict[str, Any], game_id: int, logger: logging.Logger):
        super().__init__(url, login_payload, game_id, logger)
        self.game_id = game_id
        self.login_payload = login_payload
        self.logger = logger
        self._agent: Optional[Agent] = None
        self.llm = ChatOpenAI()
        self.state = HarbergerGameState()
        self.in_market_phase = False
        self.current_phase = None
        self.market_polling_task: Optional[asyncio.Task] = None

        self.register_event_handler("assign-name", self._handle_name_assignment)
        self.register_event_handler("assign-role", self._handle_role_assignment)
        self.register_event_handler("phase-transition", self._handle_phase_transition)

        self.register_global_pre_event_hook(self._update_state)

    @property
    def agent(self) -> Optional[Agent]:
        return self._agent

    def _initialize_agent(self) -> Agent:
        """
        Create and cache the agent instance based on the assigned role.
        """
        if self._agent is None:
            if self.role == 1:
                self._agent = Speculator(
                    llm=self.llm, game_id=self.game_id, logger=self.logger, prompts_path=PATH_PROMPTS
                )
            elif self.role == 2:
                self._agent = Developer(
                    llm=self.llm, game_id=self.game_id, logger=self.logger, prompts_path=PATH_PROMPTS
                )
            elif self.role == 3:
                self._agent = Owner(llm=self.llm, game_id=self.game_id, logger=self.logger, prompts_path=PATH_PROMPTS)
            else:
                self.logger.error("Invalid role assigned; cannot initialize agent.")
                raise ValueError("Invalid role for agent initialization.")
        return self._agent

    async def _send_player_ready(self):
        """
        Send the 'player-is-ready' message so that the game can advance from the introduction.
        """
        ready_msg = {"gameId": self.game_id, "type": "player-is-ready"}
        await self.send_message(json.dumps(ready_msg))
        self.logger.info("Sent player-is-ready message.")

    # Pre-event hook for updating state
    async def _update_state(self, message: Message):
        """Update the game state when an event is received."""
        # Update the state with the event
        self.state.update(message)
        self.logger.info(f"Updated state: {self.state.model_dump_json()}")

    # Event handlers
    async def _handle_name_assignment(self, message: Message):
        """Handle the name assignment event."""
        self.name = message.data.get("name")
        self.logger.info(f"Name assigned: {self.name}")
        await self._send_player_ready()

    async def _handle_role_assignment(self, message: Message):
        """Handle the role assignment event."""
        self.role = message.data.get("role", None)
        self.logger.info(f"Role assigned: {self.role}")
        self._initialize_agent()

    async def _handle_phase_transition(self, message: Message):
        """Handle phase transition events."""
        new_phase = message.data.get("phase")
        round_number = message.data.get("round", 1)
        self.logger.info(f"Transitioning to phase {new_phase}, round {round_number}")

        if self.in_market_phase and new_phase != 6:
            self.in_market_phase = False
            if self.market_polling_task:
                self.market_polling_task.cancel()
        self.current_phase = new_phase

        if new_phase:
            await self._handle_phase(new_phase)

    async def _handle_phase(self, phase: int):
        """Handle the phase transition."""
        if not self.agent:
            return

        if phase == 6:
            self.logger.info("Entering market phase.")
            self.in_market_phase = True
            self.market_polling_task = asyncio.create_task(self._continuous_phase_loop())
        else:
            payload = await self.agent.handle_phase(phase, self.state)
            if payload:
                await self.send_message(json.dumps(payload))
                self.logger.info(f"Phase {phase} ({game_mappings.phases[phase]}), sent payload: {payload}")

    async def _continuous_phase_loop(self, min_delay: int = 10, max_delay: int = 20):
        """Runs while we are in the market phase. Asks the agent to do something every X + random offset seconds."""
        if not self.agent:
            return

        try:
            while self.in_market_phase:
                delay = random.randint(min_delay, max_delay)
                await asyncio.sleep(delay)
                payload = await self.agent.handle_phase(6, self.state)
                if payload:
                    await self.send_message(json.dumps(payload))

        except asyncio.CancelledError:
            self.logger.info("Market polling loop cancelled because phase ended.")
