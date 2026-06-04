import json
from typing import Any, Literal, Optional, Union

from dotenv import load_dotenv
from pydantic import BaseModel

from econagents import AgentRole
from econagents.core.events import Message
from econagents.core.manager.phase import TurnBasedPhaseManager
from econagents.core.state.game import GameState
from econagents.llm import ChatOpenAI

load_dotenv()


class PrisonerChoice(BaseModel):
    choice: Literal["COOPERATE", "DEFECT"]


class Prisoner(AgentRole):
    role = 1
    name = "Prisoner"
    llm = ChatOpenAI(model_name="gpt-4o-mini")
    task_phases = ["decision"]
    default_response_schema = PrisonerChoice

    def parse_phase_llm_response(self, response: Union[str, BaseModel], state: GameState) -> dict:
        if isinstance(response, PrisonerChoice):
            choice = response.choice
        else:
            choice = json.loads(response)["choice"]
        return {
            "meta": {"type": "submit-choice", "component": {"type": "standard:coordination"}},
            "payload": {"choice": choice},
        }


class PDManager(TurnBasedPhaseManager):
    def __init__(self, game_id: int, auth_mechanism_kwargs: dict[str, Any]):
        super().__init__(
            auth_mechanism_kwargs=auth_mechanism_kwargs,
            agent_role=Prisoner(),
        )
        self.game_id = game_id
        self.register_phase_handler("introduction", self._handle_introduction)

    async def _handle_introduction(self, phase: str, state: GameState) -> dict:
        return {
            "meta": {"type": "ready", "component": {"type": "standard:ready"}},
            "payload": {},
        }

    def _extract_message_data(self, raw_message: str) -> Optional[Message]:
        try:
            msg = json.loads(raw_message)
            event_type = (msg.get("meta") or {}).get("type", "")
            data = msg.get("payload") or {}
        except json.JSONDecodeError:
            self.logger.error("Invalid JSON received.")
            return None
        return Message(message_type="event", event_type=event_type, data=data)
