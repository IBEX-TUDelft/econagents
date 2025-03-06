import json
from typing import Any, cast

from econagents.core.agent_role import AgentRole
from econagents.llm.openai import ChatOpenAI
from examples.harberger.state import HarbergerGameState


class HarbergerAgent(AgentRole):
    llm = ChatOpenAI()

    def get_phase_6_user_prompt(self, state: HarbergerGameState):
        """Build the user prompt for the market phase."""

        if state.private_information.property.get("v"):
            property_value = state.private_information.property["v"][state.public_information.winning_condition]
        else:
            property_value = None

        orders = list(state.public_information.market_state.orders.values())
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
        roles_mapping = {1: "Speculator", 2: "Developer", 3: "Owner"}

        context = {
            "phase": state.meta.phase,
            "role": roles_mapping[self.role],
            "player_number": state.meta.player_number,
            "player_name": state.meta.player_name,
            "shares": state.private_information.wallet[state.public_information.winning_condition].get("shares", 0),
            "balance": state.private_information.wallet[state.public_information.winning_condition].get("balance", 0),
            "public_signal": state.public_information.public_signal[state.public_information.winning_condition],
            "private_signal": state.private_information.value_signals[state.public_information.winning_condition],
            "current_orders": sorted_orders,
            "your_orders": state.public_information.market_state.get_orders_from_player(
                cast(int, state.meta.player_number)
            ),
            "property_value": property_value,
        }
        return self.render_prompt(context=context, prompt_type="user", phase=state.meta.phase)

    def parse_phase_6_llm_response(self, response: str, state: HarbergerGameState):
        """Parse the market response."""
        response_json = json.loads(response)
        order = response_json["order"]
        order["condition"] = state.public_information.winning_condition

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


class Speculator(HarbergerAgent):
    role = 1
    name = "Speculator"
    task_phases = [3, 6, 8]

    def get_phase_3_user_prompt(self, state: HarbergerGameState):
        return self._get_speculation_user_prompt(state)

    def get_phase_8_user_prompt(self, state: HarbergerGameState):
        return self._get_speculation_user_prompt(state)

    def _get_speculation_user_prompt(self, state: HarbergerGameState):
        key = "projectA" if state.public_information.winning_condition == 1 else "noProject"

        developer_min = state.public_information.boundaries["developer"][key]["low"]
        developer_max = state.public_information.boundaries["developer"][key]["high"]
        owner_min = state.public_information.boundaries["owner"][key]["low"]
        owner_max = state.public_information.boundaries["owner"][key]["high"]

        declared_values = [
            declaration["d"][state.public_information.winning_condition]
            for declaration in state.private_information.declarations
        ]
        roles = [declaration["role"] for declaration in state.private_information.declarations]
        numbers = [declaration["number"] for declaration in state.private_information.declarations]

        percentiles = []
        for r, d in zip(roles, declared_values):
            if r == 2:
                percentiles.append(round((d - developer_min) / (developer_max - developer_min) * 100, 2))
            else:
                percentiles.append(round((d - owner_min) / (owner_max - owner_min) * 100, 2))

        roles_mapping = {1: "Speculator", 2: "Developer", 3: "Owner"}
        context = {
            "phase": state.meta.phase,
            "player_number": state.meta.player_number,
            "player_name": state.meta.player_name,
            "name": state.meta.player_name,
            "boundaries": state.public_information.boundaries,
            "winning_condition": state.public_information.winning_condition,
            "winning_condition_description": state.public_information.winning_condition_description,
            "declarations": [
                {
                    "role": roles_mapping[roles[i]],
                    "number": numbers[i],
                    "declared_value": declared_values[i],
                    "percentile": percentiles[i],
                }
                for i, _ in enumerate(state.private_information.declarations)
            ],
        }
        return self.render_prompt(context=context, prompt_type="user", phase=state.meta.phase)

    def parse_phase_3_llm_response(self, response: str, state: HarbergerGameState):
        return self._parse_speculation_response(response, state)

    def parse_phase_8_llm_response(self, response: str, state: HarbergerGameState):
        return self._parse_speculation_response(response, state)

    def _parse_speculation_response(self, response: str, state: HarbergerGameState):
        response_json = json.loads(response)
        snipe: list[list[dict[str, Any]]] = [[], []]
        snipe[state.public_information.winning_condition] = response_json["purchases"]
        return {
            "gameId": self.game_id,
            "type": "done-speculating",
            "snipe": snipe,
        }


class Developer(HarbergerAgent):
    role = 2
    name = "Developer"
    task_phases = [2, 6, 7]

    def parse_phase_2_llm_response(self, response: str, state: HarbergerGameState):
        return self._parse_declaration_response(response, state)

    def parse_phase_7_llm_response(self, response: str, state: HarbergerGameState):
        return self._parse_declaration_response(response, state)

    def _parse_declaration_response(self, response: str, state: HarbergerGameState):
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


class Owner(HarbergerAgent):
    role = 3
    name = "Owner"
    task_phases = [2, 6, 7]

    def parse_phase_2_llm_response(self, response: str, state: HarbergerGameState):
        return self._parse_declaration_response(response, state)

    def parse_phase_7_llm_response(self, response: str, state: HarbergerGameState):
        return self._parse_declaration_response(response, state)

    def _parse_declaration_response(self, response: str, state: HarbergerGameState):
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
