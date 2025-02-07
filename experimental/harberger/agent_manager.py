import asyncio
import json
import logging
import random
from dataclasses import dataclass
from typing import Any, Optional

from econagents.core.websocket import WebSocketClient
from econagents.llm.openai import ChatOpenAI
from experimental.harberger.agents import Agent, Developer, Owner, Speculator
from experimental.harberger.models import Message, State, mappings


class AgentManager(WebSocketClient):
    name: Optional[str] = None
    role: Optional[str] = None

    def __init__(self, url: str, login_payload: dict[str, Any], game_id: int, logger: logging.Logger):
        self.game_id = game_id
        self.login_payload = login_payload
        self.logger = logger
        self._agent: Optional[Agent] = None
        self.llm = ChatOpenAI()
        self.state = State()
        super().__init__(url, login_payload, game_id, logger)

    @property
    def agent(self) -> Optional[Agent]:
        return self._agent

    def _initialize_agent(self) -> Agent:
        """
        Create and cache the agent instance based on the assigned role.
        """
        if self._agent is None:
            if self.role == 1:
                self._agent = Speculator(llm=self.llm, game_id=self.game_id, logger=self.logger)
            elif self.role == 2:
                self._agent = Developer(llm=self.llm, game_id=self.game_id, logger=self.logger)
            elif self.role == 3:
                self._agent = Owner(llm=self.llm, game_id=self.game_id, logger=self.logger)
            else:
                self.logger.error("Invalid role assigned; cannot initialize agent.")
                raise ValueError("Invalid role for agent initialization.")
        return self._agent

    def _extract_message_data(self, message: str) -> Optional[Message]:
        try:
            msg = json.loads(message)
            msg_type = msg.get("type", "")
            event_type = msg.get("eventType", "")
            data = msg.get("data", {})
        except json.JSONDecodeError:
            self.logger.error("Invalid JSON received.")
            return None
        return Message(msg_type=msg_type, event_type=event_type, data=data)

    async def on_message(self, message):
        self.logger.debug(f"← Received: {message}")

        msg = self._extract_message_data(message)

        if not msg:
            return

        if msg.msg_type == "event":
            self._update_state(msg)

        if msg.msg_type == "event" and msg.event_type == "assign-name":
            self.name = msg.data.get("name")
            self.logger.info(f"Name assigned: {self.name}")
            await self._send_player_ready()

        elif msg.msg_type == "event" and msg.event_type == "assign-role":
            self.role = msg.data.get("role", None)
            self.logger.info(f"Role assigned: {self.role}")
            self._initialize_agent()

        elif msg.msg_type == "event" and msg.event_type == "players-known":
            self.known_players = msg.data.get("players", [])
            self.logger.info(f"Known players: {self.known_players}")

        elif msg.msg_type == "event" and msg.event_type == "phase-transition":
            self.current_phase = msg.data.get("phase")
            round_number = msg.data.get("round", 1)
            self.logger.info(f"Transitioning to phase {self.current_phase}, round {round_number}")
            await self._handle_phase(self.current_phase)

    def _update_state(self, event: Message):
        """Update state based on incoming event message"""
        if event.event_type == "players-known":
            self.state.players = event.data["players"]

        elif event.event_type == "phase-transition":
            self.state.phase = event.data["phase"]

        elif event.event_type == "assign-role":
            self.state.wallet = event.data["wallet"]
            self.state.boundaries = event.data["boundaries"]
            self.state.tax_rate = event.data["taxRate"]
            self.state.initial_tax_rate = event.data["initialTaxRate"]
            self.state.final_tax_rate = event.data["finalTaxRate"]
            self.state.conditions = event.data["conditions"]

        elif event.event_type == "value-signals":
            self.state.value_signals = event.data["signals"]
            self.state.public_signal = event.data["publicSignal"]
            self.state.winning_condition = event.data["condition"]
            self.state.winning_condition_description = mappings.conditions[event.data["condition"]]
            self.state.tax_rate = event.data["taxRate"]

        elif event.event_type == "assign-name":
            self.state.player_name = event.data["name"]
            self.state.player_number = event.data["number"]

        elif event.event_type == "declarations-published":
            self.state.declarations = event.data["declarations"]
            self.state.winning_condition = event.data["winningCondition"]
            self.state.winning_condition_description = mappings.conditions[event.data["winningCondition"]]
            self.state.total_declared_values = [
                sum(declaration["d"][self.state.winning_condition] for declaration in self.state.declarations)
            ]

    async def _handle_phase(self, phase: int):
        """
        Execute a simple auto-action per phase
        0 - Name assignment: All players must send "player-is-ready".
        2 - Declaration: Owners (role=3) or Developers (role=2) declare random property values.
        3 - Speculation: Speculators (role=1) might snipe random owners.
        6 - Market: (Optional) we let players place a random "ask" order.
        7 - Declaration again.
        8 - Speculation again.
        Phases 1, 4, 5, 9 do nothing in this minimal example.
        """
        if not self.agent:
            return

        payload = await self.agent.handle_phase(phase, self.state)
        if payload:
            await self.send_message(json.dumps(payload))
            self.logger.info(f"Phase {phase} ({mappings.phases[phase]}), sent payload: {payload}")

    async def _send_player_ready(self):
        """
        Send the 'player-is-ready' message so that the game can advance from the introduction.
        """
        ready_msg = {"gameId": self.game_id, "type": "player-is-ready"}
        await self.send_message(json.dumps(ready_msg))
        self.logger.info("Sent player-is-ready message.")
