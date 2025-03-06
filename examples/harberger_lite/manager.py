import json
import logging
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

from econagents import AgentRole
from econagents.core.events import Message
from econagents.core.manager.phase import HybridPhaseManager
from examples.harberger_lite.roles import Developer, Owner, Speculator
from examples.harberger_lite.state import HarbergerGameState

load_dotenv()

# This manages the interactions between the server and the agents
# It is a turn-based manager with continuous phases. It assumes that the server sends messages in the following format:
# {"message_type": <game_id>, "type": <event_type>, "data": <event_data>}
# It can be initialized with or without a role. In this case, it uses custom logic to get the role from the server.


class HarbergerAgentManager(HybridPhaseManager):
    role: Optional[str] = None

    def __init__(self, url: str, game_id: int, logger: logging.Logger, auth_mechanism_kwargs: dict[str, Any]):
        super().__init__(
            url=url,
            game_id=game_id,
            phase_transition_event="phase-transition",
            phase_identifier_key="phase",
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

    # this is needed because the current server implementation requires
    # the agent to be initialized after the role is assigned
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

    # This is required by the server
    async def _handle_name_assignment(self, message: Message):
        """Handle the name assignment event."""
        ready_msg = {"gameId": self.game_id, "type": "player-is-ready"}
        await self.send_message(json.dumps(ready_msg))

    # This is required by the server
    async def _handle_role_assignment(self, message: Message):
        """Handle the role assignment event."""
        self.role = message.data.get("role", None)
        self.logger.info(f"Role assigned: {self.role}")
        self._initialize_agent()
