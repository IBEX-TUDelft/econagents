from collections.abc import Iterable
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from econagents import Role
from econagents.runtime import Agent, create_game_state
from econagents.runtime.game_runner import GameRunnerConfig
from econagents.adapters.llm import ChatOpenAI

from examples.prisoner.state import PDGameState

load_dotenv()


class Component(BaseModel):
    type: Literal["standard:coordination"] = "standard:coordination"


class ChoiceMeta(BaseModel):
    type: Literal["submit-choice"] = "submit-choice"
    component: Component = Field(default_factory=Component)


class ChoicePayload(BaseModel):
    choice: Literal["COOPERATE", "DEFECT"]


class SubmitChoice(BaseModel):
    """The full message the prisoner emits each decision phase.

    Because this schema *is* the outbound message envelope, the default
    ``parse_phase_llm_response`` (which returns ``response.model_dump()`` for a
    structured response) produces exactly what gets sent to the server — no
    custom response parser is needed.
    """

    meta: ChoiceMeta = Field(default_factory=ChoiceMeta)
    payload: ChoicePayload


class Prisoner(Role):
    role = 1
    name = "Prisoner"
    llm = ChatOpenAI(model_name="gpt-5.4-mini")
    task_phases = ["decision"]
    default_response_schema = SubmitChoice


def create_prisoner_agent(
    *,
    config: GameRunnerConfig,
    recovery_code: str,
) -> Agent:
    """Create one Prisoner's Dilemma agent."""
    return Agent(
        url=config.server_url(),
        auth_mechanism=config.auth_mechanism,
        auth_mechanism_kwargs={"gameId": config.game_id, "recovery": recovery_code},
        state=create_game_state(PDGameState, game_id=config.game_id),
        role=Prisoner(),
        prompts_dir=config.prompts_dir,
        phase_transition_event=config.phase_transition_event,
        phase_identifier_key=config.phase_identifier_key,
        end_game_event=config.end_game_event,
    )


def create_prisoner_agents(config: GameRunnerConfig, recovery_codes: Iterable[str]) -> list[Agent]:
    """Create all Prisoner's Dilemma agents for a runner config."""
    return [create_prisoner_agent(config=config, recovery_code=code) for code in recovery_codes]
