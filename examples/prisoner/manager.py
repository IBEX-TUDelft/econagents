import json
import logging
from pathlib import Path
from typing import Any, Coroutine, Optional

from dotenv import load_dotenv

from econagents import AgentRole
from econagents.core.events import Message
from econagents.core.manager.phase import TurnBasedPhaseManager
from econagents.llm.openai import ChatOpenAI
from examples.prisoner.state import PDGameState

load_dotenv()


class Prisoner(AgentRole):
    """Base class for prisoner agents in the Prisoner's Dilemma game."""

    role = 1
    name = "Prisoner"
    llm = ChatOpenAI()


class PDManager(TurnBasedPhaseManager):
    """
    Manager for the Prisoner's Dilemma game.
    Manages interactions between the server and agents.
    """

    def __init__(self, game_id: int, auth_mechanism_kwargs: dict[str, Any]):
        super().__init__(
            auth_mechanism_kwargs=auth_mechanism_kwargs,
            state=PDGameState(game_id=game_id),
            agent_role=Prisoner(),
        )
        self.game_id = game_id
        self.register_event_handler("assign-name", self._handle_name_assignment)

    async def _handle_name_assignment(self, message: Message) -> None:
        """Handle the name assignment event."""
        ready_msg = {"gameId": self.game_id, "type": "player-is-ready"}
        if self.agent_role:
            self.agent_role.logger = self.logger
        await self.send_message(json.dumps(ready_msg))
