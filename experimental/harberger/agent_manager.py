import asyncio
import json
import logging
import random
from dataclasses import dataclass
from typing import Any, Optional

from econagents.core.websocket import WebSocketClient
from econagents.llm.openai import ChatOpenAI
from experimental.harberger.agents import Agent, Developer, Owner, Speculator
from experimental.harberger.models import Message, mappings
from experimental.harberger.state import GameState


class AgentManager(WebSocketClient):
    name: Optional[str] = None
    role: Optional[str] = None

    def __init__(self, url: str, login_payload: dict[str, Any], game_id: int, logger: logging.Logger):
        self.game_id = game_id
        self.login_payload = login_payload
        self.logger = logger
        self._agent: Optional[Agent] = None
        self.llm = ChatOpenAI()
        self.state = GameState()
        self.in_market_phase = False
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
            # Update state using the enhanced GameState class
            self.state.update_state(msg)

            if msg.event_type == "assign-name":
                self.name = msg.data.get("name")
                self.logger.info(f"Name assigned: {self.name}")
                await self._send_player_ready()

            elif msg.event_type == "assign-role":
                self.role = msg.data.get("role", None)
                self.logger.info(f"Role assigned: {self.role}")
                self._initialize_agent()

            elif msg.event_type == "players-known":
                self.known_players = msg.data.get("players", [])
                self.logger.info(f"Known players: {self.known_players}")

            elif msg.event_type == "phase-transition":
                new_phase = msg.data.get("phase")
                round_number = msg.data.get("round", 1)
                self.logger.info(f"Transitioning to phase {new_phase}, round {round_number}")

                if self.in_market_phase and new_phase != 6:
                    self.in_market_phase = False
                self.current_phase = new_phase

                await self._handle_phase(new_phase)

    async def _handle_phase(self, phase: int):
        """Handle the phase transition."""
        if not self.agent:
            return

        if phase == 6:
            self.logger.info("Entering market phase.")
            self.in_market_phase = True
            self.market_polling_task = asyncio.create_task(self._market_phase_loop())
        else:
            payload = await self.agent.handle_phase(phase, self.state)
            if payload:
                await self.send_message(json.dumps(payload))
                self.logger.info(f"Phase {phase} ({mappings.phases[phase]}), sent payload: {payload}")

    async def _market_phase_loop(self):
        """Runs while we are in the market phase. Asks the agent to do something every X + random offset seconds."""
        try:
            while self.in_market_phase:
                delay = random.uniform(15, 30)
                await asyncio.sleep(delay)

                payload = await self.agent.handle_market_phase_tick(self.state)

                if payload:
                    await self.send_message(json.dumps(payload))

        except asyncio.CancelledError:
            self.logger.info("Market polling loop cancelled because phase ended.")

    async def _send_player_ready(self):
        """
        Send the 'player-is-ready' message so that the game can advance from the introduction.
        """
        ready_msg = {"gameId": self.game_id, "type": "player-is-ready"}
        await self.send_message(json.dumps(ready_msg))
        self.logger.info("Sent player-is-ready message.")
