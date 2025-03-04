import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv

from econagents import Agent, Message, TurnBasedManager
from econagents.llm.openai import ChatOpenAI
from examples.prisoner.state import PDGameState

load_dotenv()


class Prisoner(Agent):
    """Base class for prisoner agents in the Prisoner's Dilemma game."""

    role = 1
    name = "Prisoner"
    task_phases = [1, 2, 3, 4, 5]


class PrisonersDilemmaManager(TurnBasedManager):
    """
    Manager for the Prisoner's Dilemma game.
    Manages interactions between the server and agents.
    """

    name: Optional[str] = None

    def __init__(self, url: str, login_payload: Dict[str, Any], game_id: int, logger: logging.Logger):
        super().__init__(
            url=url,
            login_payload=login_payload,
            game_id=game_id,
            phase_transition_event="round-started",
            phase_transition_event_key="round",
            logger=logger,
            state=PDGameState(game_id=game_id),
            agent=None,
            llm=ChatOpenAI(),
        )
        self.register_event_handler("assign-name", self._handle_name_assignment)

    async def _handle_name_assignment(self, message: Message) -> None:
        """Handle the name assignment event."""
        ready_msg = {"gameId": self.game_id, "type": "player-is-ready"}
        path_prompts = Path(__file__).parent / "prompts"
        if self._agent is None:
            self._agent = Prisoner(llm=self.llm, game_id=self.game_id, logger=self.logger, prompts_path=path_prompts)
        await self.send_message(json.dumps(ready_msg))
