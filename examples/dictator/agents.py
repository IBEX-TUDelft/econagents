from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from econagents import Role
from econagents.adapters.protocol import FlatMessageCodec
from econagents.runtime import Agent, create_game_state
from econagents.runtime.game_runner import GameRunnerConfig
from econagents.adapters.llm import ChatOpenAI
from examples.dictator.state import DGameState

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


class Dictator(Role):
    """Base class for players in the Dictator game."""

    role = 1
    name = "dictator"
    llm = ChatOpenAI(model_name="gpt-5.4-mini")
    response_schemas = {1: DictatorDecision, 2: DoneAction}


class Receiver(Role):
    """Class for the receiver in the Dictator game."""

    role = 2
    name = "receiver"
    llm = ChatOpenAI(model_name="gpt-5.4-mini")
    response_schemas = {2: DoneAction}

    task_phases = [2]


def create_dictator_agent(
    *,
    config: GameRunnerConfig,
    recovery_code: str,
) -> Agent:
    """Create the Dictator agent."""
    return Agent(
        url=config.server_url(),
        auth_mechanism=config.auth_mechanism,
        auth_mechanism_kwargs={"type": "join", "gameId": config.game_id, "recovery": recovery_code},
        message_codec=FlatMessageCodec(),
        state=create_game_state(DGameState, game_id=config.game_id),
        role=Dictator(),
        prompts_dir=config.prompts_dir,
        phase_transition_event=config.phase_transition_event,
        phase_identifier_key=config.phase_identifier_key,
        end_game_event=config.end_game_event,
    )


def create_receiver_agent(
    *,
    config: GameRunnerConfig,
    recovery_code: str,
) -> Agent:
    """Create the Receiver agent."""
    return Agent(
        url=config.server_url(),
        auth_mechanism=config.auth_mechanism,
        auth_mechanism_kwargs={"type": "join", "gameId": config.game_id, "recovery": recovery_code},
        message_codec=FlatMessageCodec(),
        state=create_game_state(DGameState, game_id=config.game_id),
        role=Receiver(),
        prompts_dir=config.prompts_dir,
        phase_transition_event=config.phase_transition_event,
        phase_identifier_key=config.phase_identifier_key,
        end_game_event=config.end_game_event,
    )


def create_dictator_agents(config: GameRunnerConfig, recovery_codes: list[str]) -> list[Agent]:
    """Create the Dictator and Receiver agents for a runner config."""
    if len(recovery_codes) != 2:
        raise ValueError("Dictator game requires exactly two recovery codes.")
    return [
        create_dictator_agent(config=config, recovery_code=recovery_codes[0]),
        create_receiver_agent(config=config, recovery_code=recovery_codes[1]),
    ]
