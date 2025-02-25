import json
import logging
from typing import Any, Optional

from econagents import Message, TurnAndContinuousManager, Agent
from econagents.llm.openai import ChatOpenAI
from examples.harberger.agents import Developer, Owner, Speculator
from examples.harberger.config import PATH_PROMPTS
from examples.harberger.state import HarbergerGameState


class HarbergerAgentManager(TurnAndContinuousManager):
    name: Optional[str] = None
    role: Optional[str] = None

    def __init__(self, url: str, login_payload: dict[str, Any], game_id: int, logger: logging.Logger):
        super().__init__(
            url=url,
            login_payload=login_payload,
            game_id=game_id,
            phase_transition_event="phase-transition",
            logger=logger,
            continuous_phases={6},
            min_action_delay=5,
            max_action_delay=10,
            state=HarbergerGameState(),
            agent=None,
            llm=ChatOpenAI(),
        )
        self.register_event_handler("assign-name", self._handle_name_assignment)
        self.register_event_handler("assign-role", self._handle_role_assignment)

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
