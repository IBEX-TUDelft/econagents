from collections.abc import Iterable
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from econagents import Role
from econagents.adapters.protocol import FlatMessageCodec
from econagents.runtime import Agent, create_game_state
from econagents.runtime.game_runner import GameRunnerConfig
from econagents.adapters.llm import ChatOpenAI
from examples.public_goods.state import PGGameState

load_dotenv()


class Contribution(BaseModel):
    """Phase 1 output: the player's contribution to the public good."""

    gameId: int
    type: Literal["contribution"]
    contribution: float = Field(description="Amount contributed to the public good.")


class DoneAction(BaseModel):
    """Phase 2 output: acknowledge payout."""

    gameId: int
    type: Literal["action"]
    action: Literal["done"]


class Player(Role):
    """Base class for players in the Public Goods game."""

    role = 1
    name = "player"
    llm = ChatOpenAI(model_name="gpt-5.4-mini")
    task_phases = [1, 2]
    response_schemas = {1: Contribution, 2: DoneAction}


def create_public_goods_agent(
    *,
    config: GameRunnerConfig,
    recovery_code: str,
    personality: str,
) -> Agent:
    """Create one public-goods player agent."""
    return Agent(
        url=config.server_url(),
        auth_mechanism=config.auth_mechanism,
        auth_mechanism_kwargs={"type": "join", "gameId": config.game_id, "recovery": recovery_code},
        message_codec=FlatMessageCodec(),
        role=Player(),
        state=create_game_state(PGGameState, game_id=config.game_id, personality=personality),
        prompts_dir=config.prompts_dir,
        phase_transition_event=config.phase_transition_event,
        phase_identifier_key=config.phase_identifier_key,
        end_game_event=config.end_game_event,
    )


def create_public_goods_agents(
    config: GameRunnerConfig,
    recovery_codes: Iterable[str],
    personalities: Iterable[str],
) -> list[Agent]:
    """Create all public-goods player agents for a runner config."""
    recovery_codes = list(recovery_codes)
    personalities = list(personalities)
    if len(recovery_codes) != len(personalities):
        raise ValueError("Public goods agents require one personality per recovery code.")
    return [
        create_public_goods_agent(config=config, recovery_code=code, personality=personality)
        for code, personality in zip(recovery_codes, personalities)
    ]
