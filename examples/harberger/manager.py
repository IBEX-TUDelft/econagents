import json
from typing import Any, Optional

from dotenv import load_dotenv

from econagents import AgentRole
from econagents.core.events import Message
from econagents.core.manager.phase import HybridPhaseManager
from examples.harberger.roles import Developer, Owner, Speculator
from examples.harberger.state import HLGameState

load_dotenv()

# This manages the interactions between the server and the agents
# It is a turn-based manager with continuous phases. It assumes that the server sends messages in the following format:
# {"message_type": <game_id>, "type": <event_type>, "data": <event_data>}
# It can be initialized with or without a role. In this case, it uses custom logic to get the role from the server.


class HLAgentManager(HybridPhaseManager):
    def __init__(
        self,
        game_id: int,
        auth_mechanism_kwargs: dict[str, Any],
    ):
        super().__init__(
            state=HLGameState(game_id=game_id),
            auth_mechanism_kwargs=auth_mechanism_kwargs,
        )
        self.game_id = game_id
        self.register_event_handler("assign-name", self._handle_name_assignment)
        self.register_event_handler("assign-role", self._handle_role_assignment)

    # this is needed because the current server implementation requires
    # the agent to be initialized after the role is assigned
    def _initialize_agent(self, role: int) -> None:
        """
        Create and cache the agent instance based on the assigned role.
        """
        if role == 1:
            self.agent_role = Speculator()
            self.agent_role.logger = self.logger
        elif role == 2:
            self.agent_role = Developer()
            self.agent_role.logger = self.logger
        elif role == 3:
            self.agent_role = Owner()
            self.agent_role.logger = self.logger
        else:
            self.logger.error("Invalid role assigned; cannot initialize agent.")
            raise ValueError("Invalid role for agent initialization.")

    # This is required by the server
    async def _handle_name_assignment(self, message: Message):
        """Handle the name assignment event."""
        ready_msg = {"gameId": self.game_id, "type": "player-is-ready"}
        await self.send_message(json.dumps(ready_msg))

    # This is required by the server
    async def _handle_role_assignment(self, message: Message):
        """Handle the role assignment event."""
        role = message.data.get("role")
        self.logger.info(f"Role assigned: {role}")
        self._initialize_agent(role)
