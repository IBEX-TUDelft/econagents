from typing import Any, Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from econagents import AgentRole, TurnBasedPhaseManager
from econagents.llm import ChatOpenAI

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


class Prisoner(AgentRole):
    role = 1
    name = "Prisoner"
    llm = ChatOpenAI(model_name="gpt-4o-mini")
    task_phases = ["decision"]
    default_response_schema = SubmitChoice


class PDManager(TurnBasedPhaseManager):
    """Turn-based manager for the Prisoner's Dilemma game.

    Relies entirely on the framework defaults: the connection authenticates with
    the ``join`` handshake (``JoinPayloadAuth``), inbound messages are parsed from
    the ``{"meta": ..., "payload": ...}`` envelope, the agent declares itself
    ready automatically during the ``introduction`` phase, and the LLM produces
    the outbound message envelope directly via the response schema. No custom
    auth mechanism, message parser, or response parser is configured.
    """

    def __init__(self, game_id: int, auth_mechanism_kwargs: dict[str, Any]):
        super().__init__(
            auth_mechanism_kwargs=auth_mechanism_kwargs,
            state=PDGameState(game_id=game_id),
            agent_role=Prisoner(),
        )
        self.game_id = game_id
