import json
from typing import Any, Optional

from dotenv import load_dotenv

from econagents import AgentRole
from econagents.core.events import Message
from econagents.core.manager.phase import TurnBasedPhaseManager
from econagents.llm import ChatOpenAI

load_dotenv()

PHASE_INTRODUCTION = 0
PHASE_DECISION = 1
PHASE_RESULTS = 2


VALID_CHOICES = {"loyalty", "betrayal"}


class Prisoner(AgentRole):
    """Base class for prisoner agents in the Prisoner's Dilemma game."""

    role = 1
    name = "Prisoner"
    llm = ChatOpenAI(model_name="gpt-4o", response_kwargs={"response_format": {"type": "text"}})
    task_phases = [PHASE_DECISION]

    def parse_phase_1_llm_response(self, response: str, _state: Any) -> dict:
        choice = response.strip().lower()
        if choice not in VALID_CHOICES:
            self.logger.warning(f"Unexpected LLM choice '{choice}', defaulting to 'loyalty'")
            choice = "loyalty"
        return {"meta": {"type": "submit-choice"}, "payload": {"choice": choice}}


class PDManager(TurnBasedPhaseManager):
    """
    Manager for the Prisoner's Dilemma game.
    Manages interactions between the server and agents.
    """

    def __init__(self, game_id: str, auth_mechanism_kwargs: dict[str, Any], initial_phase: int = 0):
        super().__init__(
            auth_mechanism_kwargs=auth_mechanism_kwargs,
            agent_role=Prisoner(),
        )
        self.game_id = game_id
        self._initial_phase = initial_phase
        self._bootstrapped = False
        self.register_event_handler("join:player-joined", self._bootstrap_phase)

    async def _bootstrap_phase(self, message: Message):
        if not self._bootstrapped:
            self._bootstrapped = True
            await self.handle_phase_transition(self._initial_phase)

    def _extract_message_data(self, raw_message: str) -> Optional[Message]:
        """Translate the game-engine wire format into the framework's Message model.

        The game-engine sends:
            { "type": "<event-name>", "payload": { ... }, "round": N, "phase": N }

        The base class expects message_type="event" and reads from "eventType" / "data".
        """
        try:
            msg = json.loads(raw_message)
        except json.JSONDecodeError:
            self.logger.error("Invalid JSON received.")
            return None

        event_type = msg.get("type", "")
        data = msg.get("payload", {})

        return Message(message_type="event", event_type=event_type, data=data)

    async def execute_phase_action(self, phase: int):
        if phase == PHASE_INTRODUCTION:
            await self.send_message(json.dumps({"meta": {"type": "player-is-ready"}, "payload": {}}))
        elif phase == PHASE_DECISION:
            await super().execute_phase_action(phase)
        # PHASE_RESULTS: nothing to send, wait for server timeout
