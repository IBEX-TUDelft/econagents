from typing import Any, Literal

from dotenv import load_dotenv
from pydantic import BaseModel

from econagents import AgentRole
from econagents.core.manager.phase import TurnBasedPhaseManager
from econagents.llm import ChatOpenAI

load_dotenv()


class PrisonerChoice(BaseModel):
    """Structured output the prisoner emits every round."""

    gameId: int
    type: Literal["choice"]
    choice: Literal["COOPERATE", "DEFECT"]


class Prisoner(AgentRole):
    """Base class for prisoner agents in the Prisoner's Dilemma game."""

    role = 1
    name = "Prisoner"
    llm = ChatOpenAI(model_name="gpt-5.4-mini")
    default_response_schema = PrisonerChoice


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
