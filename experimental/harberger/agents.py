import json
import logging
from abc import ABC, abstractmethod
from typing import Any, ClassVar

import numpy as np
from jinja2.sandbox import SandboxedEnvironment

from econagents.llm.openai import ChatOpenAI
from experimental.harberger.models import Message
from experimental.harberger.config import PATH_PROMPTS
from experimental.harberger.models import Mappings, State

mappings = Mappings(
    roles={
        1: "Speculator",
        2: "Developer",
        3: "Owner",
    },
    phases={
        0: "Introduction",
        1: "Presentation",
        2: "Declaration",
        3: "Speculation",
        4: "Reconciliation",
        5: "Transition",
        6: "Market",
        7: "Declaration",
        8: "Speculation",
        9: "Results",
    },
    conditions={0: "noProject", 1: "projectA"},
)


class Agent(ABC):
    role: ClassVar[int]
    name: ClassVar[str]
    llm: ChatOpenAI

    @abstractmethod
    def update_state(self, event: Message):
        pass


class HarbergerAgent(Agent):
    def __init__(self, logger: logging.Logger, llm: ChatOpenAI, game_id: int):
        self.llm = llm
        self.game_id = game_id
        self.logger = logger
        self.state = State()

    def update_state(
        self,
        event: Message,
    ):
        if event.msg_type != "event":
            return

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


class Speculator(HarbergerAgent):
    role = 1
    name = "Speculator"

    def _load_system_prompt(self):
        with (PATH_PROMPTS / "speculator_system.jinja2").open("r") as f:
            template_str = f.read()
            return SandboxedEnvironment(autoescape=True).from_string(template_str)

    def _load_user_prompt(self):
        with (PATH_PROMPTS / f"speculator_user_p{self.state.phase}.jinja2").open("r") as f:
            template_str = f.read()
            return SandboxedEnvironment(autoescape=True).from_string(template_str)

    async def handle_phase(self, phase: int):
        """
        Main phase handler that dispatches to specific phase handlers.
        """
        phase_handlers = {
            0: self._handle_introduction_phase,
            1: self._handle_presentation_phase,
            2: self._handle_declaration_phase,
            3: self._handle_speculation_phase,
            4: self._handle_reconciliation_phase,
            5: self._handle_transition_phase,
            6: self._handle_market_phase,
            7: self._handle_declaration_phase,
            8: self._handle_speculation_phase,
            9: self._handle_results_phase,
        }

        handler = phase_handlers.get(phase)
        if handler:
            return await handler()
        else:
            self.logger.warning(f"No handler implemented for phase {phase}")
            return None

    async def _handle_speculation_phase(self):
        """Handle the speculation phase (phases 3 and 8)."""
        system_prompt = self._load_system_prompt().render()
        user_prompt = self._build_speculation_user_prompt()
        messages = self.llm.build_messages(system_prompt, user_prompt)
        response = await self.llm.get_response(messages)
        self.logger.info(response)
        return self._parse_speculation_response(response)

    def _build_speculation_user_prompt(self):
        key = "projectA" if self.state.winning_condition == 1 else "noProject"

        developer_min = self.state.boundaries["developer"][key]["low"]
        developer_max = self.state.boundaries["developer"][key]["high"]
        owner_min = self.state.boundaries["owner"][key]["low"]
        owner_max = self.state.boundaries["owner"][key]["high"]

        declared_values = [declaration["d"][self.state.winning_condition] for declaration in self.state.declarations]
        roles = [declaration["role"] for declaration in self.state.declarations]
        numbers = [declaration["number"] for declaration in self.state.declarations]

        percentiles = []
        for r, d in zip(roles, declared_values):
            if r == 2:
                percentiles.append((d - developer_min) / (developer_max - developer_min) * 100)
            else:
                percentiles.append((d - owner_min) / (owner_max - owner_min) * 100)

        context = {
            "phase": self.state.phase,
            "phase_name": mappings.phases[self.state.phase],
            "player_number": self.state.player_number,
            "player_name": self.state.player_name,
            "name": self.state.player_name,
            "boundaries": self.state.boundaries,
            "winning_condition": self.state.winning_condition,
            "winning_condition_description": self.state.winning_condition_description,
            "declarations": [
                {
                    "role": mappings.roles[roles[i]],
                    "number": numbers[i],
                    "declared_value": declared_values[i],
                    "percentile": percentiles[i],
                }
                for i, declaration in enumerate(self.state.declarations)
            ],
        }
        return self._load_user_prompt().render(**context)

    def _parse_speculation_response(self, response: str):
        response_json = json.loads(response)
        snipe: list[list[dict[str, Any]]] = [[], []]
        snipe[self.state.winning_condition] = response_json["purchases"]
        payload = {
            "gameId": self.game_id,
            "type": "done-speculating",
            "snipe": snipe,
        }
        return payload

    async def _handle_introduction_phase(self):
        """Handle the introduction phase."""
        pass  # TODO: Implement introduction phase handling

    async def _handle_presentation_phase(self):
        """Handle the presentation phase."""
        pass  # TODO: Implement presentation phase handling

    async def _handle_declaration_phase(self):
        """Handle the declaration phase (phases 2 and 7)."""
        pass  # TODO: Implement declaration phase handling

    async def _handle_reconciliation_phase(self):
        """Handle the reconciliation phase."""
        pass  # TODO: Implement reconciliation phase handling

    async def _handle_transition_phase(self):
        """Handle the transition phase."""
        pass  # TODO: Implement transition phase handling

    async def _handle_market_phase(self):
        """Handle the market phase."""
        pass  # TODO: Implement market phase handling

    async def _handle_results_phase(self):
        """Handle the results phase."""
        pass  # TODO: Implement results phase handling


class Owner(HarbergerAgent):
    role = 3
    name = "Owner"

    async def handle_phase(self, phase: int):
        """Main phase handler that dispatches to specific phase handlers."""
        if phase == 2 or phase == 7:
            return await self._handle_declaration_phase()
        return None

    async def _handle_declaration_phase(self):
        """Handle the declaration phase by generating random values within boundaries."""
        declarations = []
        for condition in ["noProject", "projectA"]:
            min_value = self.state.boundaries["owner"][condition]["low"]
            max_value = self.state.boundaries["owner"][condition]["high"]
            declarations.append(int(np.random.uniform(min_value, max_value)))
        declarations.append(0)
        payload = {
            "gameId": self.game_id,
            "type": "declare",
            "declaration": declarations,
        }
        return payload


class Developer(HarbergerAgent):
    role = 2
    name = "Developer"

    async def handle_phase(self, phase: int):
        """Main phase handler that dispatches to specific phase handlers."""
        if phase == 2 or phase == 7:
            return await self._handle_declaration_phase()
        return None

    async def _handle_declaration_phase(self):
        """Handle the declaration phase by generating random values within boundaries."""
        declarations = []
        for condition in ["noProject", "projectA"]:
            min_value = self.state.boundaries["developer"][condition]["low"]
            max_value = self.state.boundaries["developer"][condition]["high"]
            declarations.append(int(np.random.uniform(min_value, max_value)))
        declarations.append(0)
        payload = {
            "gameId": self.game_id,
            "type": "declare",
            "declaration": declarations,
        }
        return payload
