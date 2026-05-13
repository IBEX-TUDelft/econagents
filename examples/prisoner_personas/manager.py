"""Code-driven role + manager for the persona-driven prisoner example."""

from typing import Any, Literal, Optional

from dotenv import load_dotenv
from pydantic import BaseModel

from econagents import AgentRole
from econagents.core.manager.phase import TurnBasedPhaseManager
from econagents.llm import ChatOpenAI
from econagents.personas import Persona

load_dotenv()


class PrisonerChoice(BaseModel):
    """Structured output the prisoner emits every round."""

    gameId: int
    type: Literal["choice"]
    choice: Literal["COOPERATE", "DEFECT"]


class Prisoner(AgentRole):
    """Single neutral prisoner role; behavior is driven by the attached persona."""

    role = 1
    name = "Prisoner"
    llm = ChatOpenAI(model_name="gpt-5.4-mini")
    default_response_schema = PrisonerChoice


class PDManager(TurnBasedPhaseManager):
    """Manager that pairs a Prisoner role instance with a per-agent persona."""

    def __init__(
        self,
        game_id: int,
        auth_mechanism_kwargs: dict[str, Any],
        persona: Optional[Persona] = None,
    ):
        super().__init__(
            auth_mechanism_kwargs=auth_mechanism_kwargs,
            agent_role=Prisoner(persona=persona),
        )
        self.game_id = game_id
