import json
from typing import Any

from dotenv import load_dotenv

from econagents import AgentRole
from econagents.core.events import Message
from econagents.core.manager.phase import TurnBasedPhaseManager
from econagents.llm import ChatOpenAI

load_dotenv()


class Dictator(AgentRole):
    """Base class for players in the Dictator game."""

    role = 1
    name = "dictator"
    llm = ChatOpenAI(model_name="gpt-4.1-mini")


class Receiver(AgentRole):
    """Class for the receiver in the Dictator game."""

    role = 2
    name = "receiver"
    llm = ChatOpenAI(model_name="gpt-4.1-mini")

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
