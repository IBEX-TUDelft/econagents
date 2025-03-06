import json
import logging
from pathlib import Path
from typing import Any, Optional

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

    name: Optional[str] = None

    def __init__(self, url: str, game_id: int, logger: logging.Logger, auth_mechanism_kwargs: dict[str, Any]):
        super().__init__(
            url=url,
            game_id=game_id,
            phase_transition_event="round-started",
            phase_identifier_key="round",
            auth_mechanism_kwargs=auth_mechanism_kwargs,
            logger=logger,
            state=PDGameState(game_id=game_id),
            agent=Prisoner(game_id=game_id, logger=logger, prompts_path=Path(__file__).parent / "prompts"),
        )
        self.register_event_handler("assign-name", self._handle_name_assignment)

    async def _handle_name_assignment(self, message: Message) -> None:
        """Handle the name assignment event."""
        ready_msg = {"gameId": self.game_id, "type": "player-is-ready"}
        await self.send_message(json.dumps(ready_msg))
