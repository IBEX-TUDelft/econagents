import json
import logging
from abc import ABC, abstractmethod
from typing import Any, ClassVar

import numpy as np
from jinja2.sandbox import SandboxedEnvironment

from econagents.llm.openai import ChatOpenAI
from experimental.harberger.config import PATH_PROMPTS
from experimental.harberger.models import mappings
from experimental.harberger.state import GameState


class Agent(ABC):  #SR: part of any game
    role: ClassVar[int]     #SR: part of any game
    name: ClassVar[str]     #SR: part of any game
    llm: ChatOpenAI         #SR: part of any game

    @abstractmethod
    async def handle_phase(self, phase: int, state: GameState):
        """Base implementation of state update handler"""
        pass

    @abstractmethod  #SR: part of market games, or continuous games
    async def handle_market_phase_tick(self, state: GameState):
        """Handle the market phase tick."""
        pass

   #SR: agent handler concept is general, here I see components that are game specific come back. 
class HarbergerAgent(Agent):  
    def __init__(self, logger: logging.Logger, llm: ChatOpenAI, game_id: int):
        self.llm = llm
        self.game_id = game_id
        self.logger = logger

    def _load_system_prompt(self, filename: str):
        with (PATH_PROMPTS / filename).open("r") as f:
            template_str = f.read()
            return SandboxedEnvironment(autoescape=True).from_string(template_str)

    def _load_user_prompt(self, filename: str):
        with (PATH_PROMPTS / filename).open("r") as f:
            template_str = f.read()
            return SandboxedEnvironment(autoescape=True).from_string(template_str)
     #SR: part of any game, but it assumes that the phase is a turn-based system 
     #SR: by turn-based I mean that tasks gets to executed in isolation, and the results are determined after all tasks are completed
    async def handle_phase(self, phase: int, state: GameState):
        """
        Main phase handler that dispatches to specific phase handlers.
        Must be implemented by subclasses.
        """
        pass
    #SR: here we have the market as a specific case of a time-based (not turn-based) phase. Actions/choices here cause a direct change in the game state. 
    #SR: for reuse it might make sense to define turn-based tasks and time-based tasks seperately as reusuable components. You lready do this for turnbase phase handlers by the looks of it
    async def _build_market_user_prompt(self, state: GameState):
        """Build the user prompt for the market phase."""
        
        if state.property.get("v"):  #SR: game specific, private information
            property_value = state.property["v"][state.winning_condition]
        else:
            property_value = None

        orders = list(state.market.orders.values()) #SR: game specific, public information
        asks = sorted(
            [order for order in orders if order.type == "ask"],
            key=lambda x: x.price,
            reverse=True,  # Lowest ask first
        )
        bids = sorted(
            [order for order in orders if order.type == "bid"],
            key=lambda x: x.price,
            reverse=True,  # Highest bid first
        )
        sorted_orders = asks + bids

        context = {
            #SR: General information, meta and proces information
            "phase": state.phase,
            "phase_name": mappings.phases[state.phase],  
            "role": mappings.roles[self.role],
            "player_number": state.player_number,
            "player_name": state.player_name,
            #SR: Game specific information
            "shares": state.wallet[state.winning_condition].get("shares", 0),           #SR: private information
            "balance": state.wallet[state.winning_condition].get("balance", 0),         #SR: private information
            "public_signal": state.public_signal[state.winning_condition],              #SR: public information
            "private_signal": state.value_signals[state.winning_condition],             #SR: private information
            "current_orders": sorted_orders,                                            #SR: public information
            "your_orders": state.market.get_orders_from_player(state.player_number),    #SR: private information
            "property_value": property_value,                                           #SR: private information
        }
        return self._load_user_prompt("all_user_p6.jinja2").render(**context)

    async def handle_market_phase_tick(self, state: GameState):
        """Handle the market phase tick."""
        messages = self.llm.build_messages(
            system_prompt=self._load_system_prompt("all_system_p6.jinja2").render(),
            user_prompt=await self._build_market_user_prompt(state),
        )
        response = await self.llm.get_response(
            messages=messages,
            tracing_extra={
                "game_id": self.game_id,
                "phase": state.phase,
                "role": self.role,
                "player_number": state.player_number,
                "player_name": state.player_name,
            },
        )
        return self._parse_market_response(response, state)

    def _parse_market_response(self, response: str, state: GameState):
        """Parse the market response."""
        response_json = json.loads(response)
        order = response_json["order"]
        order["condition"] = state.winning_condition
        if response_json["action"] == "post-order":
            return {
                "gameId": self.game_id,
                "type": "post-order",
                "order": order,
            }
        elif response_json["action"] == "cancel-order":
            return {
                "gameId": self.game_id,
                "type": "cancel-order",
                "order": order,
            }
        elif response_json["action"] == "do-nothing":
            return {}
        else:
            raise ValueError(f"Unknown action: {response_json['action']}")

  #SR: Roles are game specific, and this is unlikely to get much reuse
class Speculator(HarbergerAgent):
    role = 1
    name = "Speculator"

    async def handle_phase(self, phase: int, state: GameState):
        """
        Main phase handler that dispatches to specific phase handlers.
        """
        if phase == 3 or phase == 8:
            return await self._handle_speculation_phase(state)
        return None

    async def _handle_speculation_phase(self, state: GameState):
        """Handle the speculation phase (phases 3 and 8)."""
        system_prompt = self._load_system_prompt("speculator_system.jinja2").render()
        user_prompt = self._build_speculation_user_prompt(state)
        messages = self.llm.build_messages(system_prompt, user_prompt)
        response = await self.llm.get_response(
            messages=messages,
            tracing_extra={
                "game_id": self.game_id,
                "phase": state.phase,
                "role": self.role,
                "player_number": state.player_number,
                "player_name": state.player_name,
            },
        )
        return self._parse_speculation_response(response, state)

    def _build_speculation_user_prompt(self, state: GameState):
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
                percentiles.append(round((d - developer_min) / (developer_max - developer_min) * 100, 2))
            else:
                percentiles.append(round((d - owner_min) / (owner_max - owner_min) * 100, 2))

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
        return self._load_user_prompt(f"speculator_user_p{state.phase}.jinja2").render(**context)

    def _parse_speculation_response(self, response: str, state: GameState):
        response_json = json.loads(response)
        snipe: list[list[dict[str, Any]]] = [[], []]
        snipe[state.winning_condition] = response_json["purchases"]
        payload = {
            "gameId": self.game_id,
            "type": "done-speculating",
            "snipe": snipe,
        }
        return payload

    async def _handle_market_phase(self, state: GameState):
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

    async def _handle_results_phase(self, state: GameState):
        """Handle the results phase."""
        pass


class Owner(HarbergerAgent):
    role = 3
    name = "Owner"

    async def handle_phase(self, phase: int, state: GameState):
        """Main phase handler that dispatches to specific phase handlers."""
        if phase == 2 or phase == 7:
            return await self._handle_declaration_phase(state)
        return None

    async def _handle_declaration_phase(self, state: GameState):
        """Handle the declaration phase using LLM."""
        system_prompt = self._load_system_prompt("owner_system.jinja2").render()
        user_prompt = self._build_declaration_user_prompt(state)
        messages = self.llm.build_messages(system_prompt, user_prompt)
        response = await self.llm.get_response(
            messages=messages,
            tracing_extra={
                "game_id": self.game_id,
                "phase": state.phase,
                "role": self.role,
                "player_number": state.player_number,
                "player_name": state.player_name,
            },
        )
        return self._parse_declaration_response(response)

    def _build_declaration_user_prompt(self, state: GameState):
        context = {
            "phase": state.phase,
            "phase_name": mappings.phases[state.phase],
            "player_number": state.player_number,
            "player_name": state.player_name,
            "conditions": state.conditions,
            "property": state.property,
            "boundaries": state.boundaries,
            "tax_rate": state.tax_rate,
            "winning_condition": state.winning_condition,
            "winning_condition_description": state.winning_condition_description,
            "declarations": state.declarations,
            "public_signal": state.public_signal,
            "value_signals": state.value_signals,
        }
        return self._load_user_prompt(f"owner_user_p{state.phase}.jinja2").render(**context)

    def _parse_declaration_response(self, response: str):
        response_json = json.loads(response)
        payload = {
            "gameId": self.game_id,
            "type": "declare",
            "declaration": [
                response_json["value_no_project"],
                response_json["value_project"],
                0,
            ],
        }
        return payload


class Developer(HarbergerAgent):
    role = 2
    name = "Developer"

    async def handle_phase(self, phase: int, state: GameState):
        """Main phase handler that dispatches to specific phase handlers."""
        if phase == 2 or phase == 7:
            return await self._handle_declaration_phase(state)
        return None

    async def _handle_declaration_phase(self, state: GameState):
        """Handle the declaration phase using LLM."""
        system_prompt = self._load_system_prompt("developer_system.jinja2").render()
        user_prompt = self._build_declaration_user_prompt(state)
        messages = self.llm.build_messages(system_prompt, user_prompt)
        response = await self.llm.get_response(
            messages=messages,
            tracing_extra={
                "game_id": self.game_id,
                "phase": state.phase,
                "role": self.role,
                "player_number": state.player_number,
                "player_name": state.player_name,
            },
        )
        return self._parse_declaration_response(response)

    def _build_declaration_user_prompt(self, state: GameState):
        context = {
            "phase": state.phase,
            "phase_name": mappings.phases[state.phase],
            "player_number": state.player_number,
            "player_name": state.player_name,
            "conditions": state.conditions,
            "property": state.property,
            "boundaries": state.boundaries,
            "initial_tax_rate": state.initial_tax_rate,
            "final_tax_rate": state.final_tax_rate,
            "winning_condition": state.winning_condition,
            "winning_condition_description": state.winning_condition_description,
            "declarations": state.declarations,
            "public_signal": state.public_signal,
            "value_signals": state.value_signals,
        }
        return self._load_user_prompt(f"developer_user_p{state.phase}.jinja2").render(**context)

    def _parse_declaration_response(self, response: str):
        response_json = json.loads(response)
        payload = {
            "gameId": self.game_id,
            "type": "declare",
            "declaration": [
                response_json["value_no_project"],
                response_json["value_project"],
                0,
            ],
        }
        return payload
