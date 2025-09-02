from typing import Any

from dotenv import load_dotenv

from econagents import AgentRole
from econagents.core.manager.phase import TurnBasedPhaseManager
from econagents.llm import ChatOpenAI
from examples.public_goods.state import PGGameState

load_dotenv()


class Player(AgentRole):
    """Base class for players in the Public Goods game."""

    role = 1
    name = "player"
    llm = ChatOpenAI(model_name="gpt-4.1-mini", response_kwargs={"temperature": 1})
    task_phases = [1, 2]


class PublicGoodsManager(TurnBasedPhaseManager):
    """
    Manager for players in the Public Goods game.
    Manages interactions between the server and agents.
    """

    def __init__(
        self,
        game_id: int,
        auth_mechanism_kwargs: dict[str, Any],
        player_number: int,
        personality: str,
    ):
        super().__init__(
            auth_mechanism_kwargs=auth_mechanism_kwargs,
            agent_role=Player(),
            state=PGGameState(personality=personality),
        )
        self.game_id = game_id
        self.player_number = player_number
