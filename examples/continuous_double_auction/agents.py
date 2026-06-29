from collections.abc import Iterable
import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from econagents import Role
from econagents.adapters.llm import ChatOpenAI
from econagents.runtime import Agent, PhaseEngine, create_game_state
from econagents.runtime.game_runner import GameRunnerConfig, HybridGameRunnerConfig

from examples.continuous_double_auction.state import CDAGameState

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env", override=True)

MARKET_PHASE = "market"
SUMMARY_PHASE = "summary"


class OrderComponent(BaseModel):
    """Component marker for CDA order actions."""

    type: Literal["continuous-double-auction:order"] = "continuous-double-auction:order"


class OrderMeta(BaseModel):
    """Outbound action metadata emitted by the trader LLM."""

    type: Literal["submit-order", "hold"]
    component: OrderComponent = Field(default_factory=OrderComponent)


class OrderPayload(BaseModel):
    """Outbound action payload emitted by the trader LLM."""

    gameId: int
    side: Literal["buy", "sell"] | None = None
    price: float | None = Field(default=None, description="Bid or ask price. Required for submit-order.")
    reason: str | None = Field(default=None, description="Short reason when holding instead of quoting.")


class MarketAction(BaseModel):
    """Structured action emitted by an LLM trader during the continuous market."""

    meta: OrderMeta
    payload: OrderPayload


class Trader(Role[CDAGameState]):
    """LLM-backed trader role for the local continuous double auction."""

    role = 1
    name = "trader"
    llm = ChatOpenAI(
        model_name=os.getenv("OPENAI_MODEL", "gpt-5.4-mini"),
        response_kwargs={"max_output_tokens": 300},
    )
    task_phases = [MARKET_PHASE]
    response_schemas = {MARKET_PHASE: MarketAction}


def create_cda_agent(*, config: GameRunnerConfig, recovery_code: str) -> Agent:
    """Create one LLM-backed continuous double auction trader."""
    if not isinstance(config, HybridGameRunnerConfig):
        raise TypeError("The continuous double auction example requires HybridGameRunnerConfig.")

    return Agent(
        url=config.server_url(),
        auth_mechanism=config.auth_mechanism,
        auth_mechanism_kwargs={"gameId": config.game_id, "recovery": recovery_code},
        state=create_game_state(CDAGameState, game_id=config.game_id),
        role=Trader(),
        prompts_dir=config.prompts_dir,
        phase_transition_event=config.phase_transition_event,
        phase_identifier_key=config.phase_identifier_key,
        phase_engine=PhaseEngine(
            continuous_phases=set(config.continuous_phases),
            min_action_delay=config.min_action_delay,
            max_action_delay=config.max_action_delay,
        ),
        end_game_event=config.end_game_event,
    )


def create_cda_agents(config: GameRunnerConfig, recovery_codes: Iterable[str]) -> list[Agent]:
    """Create all traders for a runner config."""
    return [create_cda_agent(config=config, recovery_code=code) for code in recovery_codes]
