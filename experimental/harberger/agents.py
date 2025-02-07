import json
import logging
from abc import ABC, abstractmethod
from typing import Any, ClassVar

import numpy as np
from jinja2.sandbox import SandboxedEnvironment

from econagents.llm.openai import ChatOpenAI
from experimental.harberger.models import Message, mappings
from experimental.harberger.config import PATH_PROMPTS
from experimental.harberger.models import State


class Agent(ABC):
    role: ClassVar[int]
    name: ClassVar[str]
    llm: ChatOpenAI

    @abstractmethod
    async def handle_phase(self, phase: int, state: State):
        """Base implementation of state update handler"""
        pass


class HarbergerAgent(Agent):
    def __init__(self, logger: logging.Logger, llm: ChatOpenAI, game_id: int):
        self.llm = llm
        self.game_id = game_id
        self.logger = logger

    async def handle_phase(self, phase: int, state: State):
        """
        Main phase handler that dispatches to specific phase handlers.
        Must be implemented by subclasses.
        """
        pass


class Speculator(HarbergerAgent):
    role = 1
    name = "Speculator"

    def _load_system_prompt(self):
        with (PATH_PROMPTS / "speculator_system.jinja2").open("r") as f:
            template_str = f.read()
            return SandboxedEnvironment(autoescape=True).from_string(template_str)

    def _load_user_prompt(self, phase: int):
        with (PATH_PROMPTS / f"speculator_user_p{phase}.jinja2").open("r") as f:
            template_str = f.read()
            return SandboxedEnvironment(autoescape=True).from_string(template_str)

    async def handle_phase(self, phase: int, state: State):
        """
        Main phase handler that dispatches to specific phase handlers.
        """
        if phase == 3 or phase == 8:
            return await self._handle_speculation_phase(state)
        if phase == 6:
            return await self._handle_market_phase(state)
        return None

    async def _handle_speculation_phase(self, state: State):
        """Handle the speculation phase (phases 3 and 8)."""
        system_prompt = self._load_system_prompt().render()
        user_prompt = self._build_speculation_user_prompt(state)
        messages = self.llm.build_messages(system_prompt, user_prompt)
        response = await self.llm.get_response(messages)
        self.logger.info(response)
        return self._parse_speculation_response(response, state)

    def _build_speculation_user_prompt(self, state: State):
        key = "projectA" if state.winning_condition == 1 else "noProject"

        developer_min = state.boundaries["developer"][key]["low"]
        developer_max = state.boundaries["developer"][key]["high"]
        owner_min = state.boundaries["owner"][key]["low"]
        owner_max = state.boundaries["owner"][key]["high"]

        declared_values = [declaration["d"][state.winning_condition] for declaration in state.declarations]
        roles = [declaration["role"] for declaration in state.declarations]
        numbers = [declaration["number"] for declaration in state.declarations]

        percentiles = []
        for r, d in zip(roles, declared_values):
            if r == 2:
                percentiles.append((d - developer_min) / (developer_max - developer_min) * 100)
            else:
                percentiles.append((d - owner_min) / (owner_max - owner_min) * 100)

        context = {
            "phase": state.phase,
            "phase_name": mappings.phases[state.phase],
            "player_number": state.player_number,
            "player_name": state.player_name,
            "name": state.player_name,
            "boundaries": state.boundaries,
            "winning_condition": state.winning_condition,
            "winning_condition_description": state.winning_condition_description,
            "declarations": [
                {
                    "role": mappings.roles[roles[i]],
                    "number": numbers[i],
                    "declared_value": declared_values[i],
                    "percentile": percentiles[i],
                }
                for i, _ in enumerate(state.declarations)
            ],
        }
        return self._load_user_prompt(state.phase).render(**context)

    def _parse_speculation_response(self, response: str, state: State):
        response_json = json.loads(response)
        snipe: list[list[dict[str, Any]]] = [[], []]
        snipe[state.winning_condition] = response_json["purchases"]
        payload = {
            "gameId": self.game_id,
            "type": "done-speculating",
            "snipe": snipe,
        }
        return payload

    async def _handle_market_phase(self, state: State):
        payload = {
            "gameId": self.game_id,
            "type": "post-order",
            "order": {
                "price": 100,
                "quantity": 4,
                "condition": state.winning_condition,
                "type": "ask",
                "now": False,
            },
        }
        return payload

    async def _handle_results_phase(self, state: State):
        """Handle the results phase."""
        pass


class Owner(HarbergerAgent):
    role = 3
    name = "Owner"

    async def handle_phase(self, phase: int, state: State):
        """Main phase handler that dispatches to specific phase handlers."""
        if phase == 2 or phase == 7:
            return await self._handle_declaration_phase(state)
        if phase == 6:
            return await self._handle_market_phase(state)
        return None

    async def _handle_declaration_phase(self, state: State):
        """Handle the declaration phase by generating random values within boundaries."""
        declarations = []
        for condition in ["noProject", "projectA"]:
            min_value = state.boundaries["owner"][condition]["low"]
            max_value = state.boundaries["owner"][condition]["high"]
            declarations.append(int(np.random.uniform(min_value, max_value)))
        declarations.append(0)
        payload = {
            "gameId": self.game_id,
            "type": "declare",
            "declaration": declarations,
        }
        return payload

    async def _handle_market_phase(self, state: State):
        """Handle the market phase."""
        payload = {
            "gameId": self.game_id,
            "type": "post-order",
            "order": {
                "price": 100,
                "quantity": 2,
                "condition": state.winning_condition,
                "type": "bid",
                "now": False,
            },
        }
        return payload


class Developer(HarbergerAgent):
    role = 2
    name = "Developer"

    async def handle_phase(self, phase: int, state: State):
        """Main phase handler that dispatches to specific phase handlers."""
        if phase == 2 or phase == 7:
            return await self._handle_declaration_phase(state)
        if phase == 6:
            return await self._handle_market_phase(state)
        return None

    async def _handle_market_phase(self, state: State):
        """Handle the market phase."""
        payload = {
            "gameId": self.game_id,
            "type": "post-order",
            "order": {
                "price": 100,
                "quantity": 1,
                "condition": state.winning_condition,
                "type": "bid",
                "now": True,
            },
        }
        return payload

    async def _handle_declaration_phase(self, state: State):
        """Handle the declaration phase by generating random values within boundaries."""
        declarations = []
        for condition in ["noProject", "projectA"]:
            min_value = state.boundaries["developer"][condition]["low"]
            max_value = state.boundaries["developer"][condition]["high"]
            declarations.append(int(np.random.uniform(min_value, max_value)))
        declarations.append(0)
        payload = {
            "gameId": self.game_id,
            "type": "declare",
            "declaration": declarations,
        }
        return payload
