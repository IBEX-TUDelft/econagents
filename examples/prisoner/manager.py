import json
from typing import Any

from dotenv import load_dotenv

from econagents import AgentRole
from econagents.core.events import Message
from econagents.core.manager.phase import TurnBasedPhaseManager
from econagents.llm import ChatOpenAI

load_dotenv()


class Prisoner(AgentRole):
    """Base class for prisoner agents in the Prisoner's Dilemma game."""

    role = 1
    name = "Prisoner"
    llm = ChatOpenAI(model_name="gpt-4o")


class PDManager(TurnBasedPhaseManager):
    """
    Manager for the Prisoner's Dilemma game.
    Manages interactions between the server and agents.
    """

    def __init__(self, game_id: int, auth_mechanism_kwargs: dict[str, Any]):
        super().__init__(
            auth_mechanism_kwargs=auth_mechanism_kwargs,
            agent_role=Prisoner(),
        )
        self.game_id = game_id
        self.register_event_handler("assign-name", self._handle_name_assignment)

    async def _handle_name_assignment(self, message: Message) -> None:
        """Handle the name assignment event."""
        ready_msg = {"gameId": self.game_id, "type": "player-is-ready"}
        await self.send_message(json.dumps(ready_msg))
