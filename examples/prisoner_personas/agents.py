"""Code-driven role and agent factory for the persona-driven prisoner example."""

from collections.abc import Iterable
from typing import Literal, Optional

from dotenv import load_dotenv
from pydantic import BaseModel

from econagents import Role
from econagents.runtime import Agent, create_game_state
from econagents.runtime.game_runner import GameRunnerConfig
from econagents.adapters.llm import ChatOpenAI
from econagents.personas import Persona
from examples.prisoner.state import PDGameState

load_dotenv()


class PrisonerChoice(BaseModel):
    """Structured output the prisoner emits every round."""

    gameId: int
    type: Literal["choice"]
    choice: Literal["COOPERATE", "DEFECT"]


class Prisoner(Role):
    """Single neutral prisoner role; behavior is driven by the attached persona."""

    role = 1
    name = "Prisoner"
    llm = ChatOpenAI(model_name="gpt-5.4-mini")
    default_response_schema = PrisonerChoice


def create_prisoner_persona_agent(
    *,
    config: GameRunnerConfig,
    recovery_code: str,
    persona: Optional[Persona],
) -> Agent:
    """Create one persona-driven prisoner agent."""
    return Agent(
        url=config.server_url(),
        auth_mechanism=config.auth_mechanism,
        auth_mechanism_kwargs={"gameId": config.game_id, "recovery": recovery_code},
        state=create_game_state(PDGameState, game_id=config.game_id),
        role=Prisoner(persona=persona),
        prompts_dir=config.prompts_dir,
        phase_transition_event=config.phase_transition_event,
        phase_identifier_key=config.phase_identifier_key,
        end_game_event=config.end_game_event,
    )


def create_prisoner_persona_agents(
    config: GameRunnerConfig,
    recovery_codes: Iterable[str],
    personas: Iterable[Optional[Persona]],
) -> list[Agent]:
    """Create all persona-driven prisoner agents for a runner config."""
    recovery_codes = list(recovery_codes)
    personas = list(personas)
    if len(recovery_codes) != len(personas):
        raise ValueError("Persona prisoner agents require one persona per recovery code.")
    return [
        create_prisoner_persona_agent(config=config, recovery_code=recovery_code, persona=persona)
        for recovery_code, persona in zip(recovery_codes, personas)
    ]
