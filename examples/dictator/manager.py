from typing import Any, Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from econagents import AgentRole
from econagents.core.manager.phase import TurnBasedPhaseManager
from econagents.llm import ChatOpenAI

load_dotenv()


class DictatorDecision(BaseModel):
    """Phase 1 output for the Dictator."""

    gameId: int
    type: Literal["decision"]
    money_send: float = Field(description="Amount of money sent to the Receiver, must be >= 0.")


class DoneAction(BaseModel):
    """Terminal acknowledgment sent at the end of the game."""

    gameId: int
    type: Literal["action"]
    action: Literal["done"]


class Dictator(AgentRole):
    """Base class for players in the Dictator game."""

    role = 1
    name = "dictator"
    llm = ChatOpenAI(model_name="gpt-5.4-mini")
    response_schemas = {1: DictatorDecision, 2: DoneAction}


class Receiver(AgentRole):
    """Class for the receiver in the Dictator game."""

    role = 2
    name = "receiver"
    llm = ChatOpenAI(model_name="gpt-5.4-mini")
    response_schemas = {2: DoneAction}

    task_phases = [2]


class DictatorManager(TurnBasedPhaseManager):
    """
    Manager for the Dictator game.
    Manages interactions between the server and agents.
    """

    def __init__(self, game_id: int, auth_mechanism_kwargs: dict[str, Any]):
        super().__init__(
            auth_mechanism_kwargs=auth_mechanism_kwargs,
            agent_role=Dictator(),
        )
        self.game_id = game_id


class ReceiverManager(TurnBasedPhaseManager):
    """
    Manager for the Receiver in the Dictator game.
    Manages interactions between the server and agents.
    """

    def __init__(self, game_id: int, auth_mechanism_kwargs: dict[str, Any]):
        super().__init__(
            auth_mechanism_kwargs=auth_mechanism_kwargs,
            agent_role=Receiver(),
        )
        self.game_id = game_id
