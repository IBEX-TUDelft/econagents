import json
import logging
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

from econagents import AgentRole
from econagents.core.events import Message
from econagents.core.manager.phase import HybridPhaseManager
from econagents.llm.openai import ChatOpenAI
from examples.harberger.roles import Developer, Owner, Speculator
from examples.harberger.state import HarbergerGameState

load_dotenv()


class HarbergerAgentManager(HybridPhaseManager):
    role: Optional[str] = None

    def __init__(self, url: str, game_id: int, logger: logging.Logger, auth_mechanism_kwargs: dict[str, Any]):
        super().__init__(
            url=url,
            game_id=game_id,
            phase_transition_event="phase-transition",
            logger=logger,
            auth_mechanism_kwargs=auth_mechanism_kwargs,
            continuous_phases={6},
            min_action_delay=5,
            max_action_delay=10,
            state=HarbergerGameState(game_id=game_id),
            agent=None,
        )
        self.register_event_handler("assign-name", self._handle_name_assignment)
        self.register_event_handler("assign-role", self._handle_role_assignment)

    def _initialize_agent(self) -> AgentRole:
        """
        Create and cache the agent instance based on the assigned role.
        """
        path_prompts = Path(__file__).parent / "prompts"
        if self._agent is None:
            if self.role == 1:
                self._agent = Speculator(game_id=self.game_id, logger=self.logger, prompts_path=path_prompts)
            elif self.role == 2:
                self._agent = Developer(game_id=self.game_id, logger=self.logger, prompts_path=path_prompts)
            elif self.role == 3:
                self._agent = Owner(game_id=self.game_id, logger=self.logger, prompts_path=path_prompts)
            else:
                self.logger.error("Invalid role assigned; cannot initialize agent.")
                raise ValueError("Invalid role for agent initialization.")
        return self._agent

    async def _handle_name_assignment(self, message: Message):
        """Handle the name assignment event."""
        ready_msg = {"gameId": self.game_id, "type": "player-is-ready"}
        await self.send_message(json.dumps(ready_msg))

    async def _handle_role_assignment(self, message: Message):
        """Handle the role assignment event."""
        self.role = message.data.get("role", None)
        self.logger.info(f"Role assigned: {self.role}")
        self._initialize_agent()
