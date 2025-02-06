import logging

import pytest

from econagents.llm import ChatOpenAI
from experimental.harberger.agents import Speculator
from experimental.harberger.config import OPENAI_API_KEY
from experimental.harberger.tests.fixtures import game_sequence_speculator


@pytest.fixture
def agent():
    logger = logging.getLogger("test_logger")
    llm = ChatOpenAI(api_key=OPENAI_API_KEY)
    return Speculator(logger=logger, llm=llm, game_id=1)


def test_assign_name_event(agent):
    event = {"type": "event", "eventType": "assign-name", "data": {"name": "Red", "number": 6, "ruleset": "Harberger"}}
    agent.update_state(event)
    assert agent.state.player_name == "Red"
    assert agent.state.player_number == 6


def test_assign_role_event(agent):
    event = {
        "type": "event",
        "eventType": "assign-role",
        "data": {
            "role": 1,
            "wallet": [
                {"balance": 50000, "shares": 5, "cashForSniping": 250000},
                {"balance": 50000, "shares": 5, "cashForSniping": 250000},
                {"balance": 50000, "shares": 5, "cashForSniping": 250000},
            ],
            "boundaries": {
                "developer": {
                    "noProject": {"low": 200000, "high": 500000},
                    "projectA": {"low": 500000, "high": 2750000},
                },
                "owner": {"noProject": {"low": 350000, "high": 600000}, "projectA": {"low": 150000, "high": 350000}},
            },
            "taxRate": 1,
            "initialTaxRate": 1,
            "finalTaxRate": 33,
            "conditions": [
                {"name": "No Project", "id": 0, "parameter": "no_project", "key": "noProject"},
                {"name": "Project", "id": 1, "parameter": "project_a", "key": "projectA"},
            ],
        },
    }
    agent.update_state(event)
    assert agent.state.wallet["balance"] == 50000
    assert agent.state.wallet["shares"] == 5
    assert agent.state.wallet["cashForSniping"] == 250000
    assert agent.state.tax_rate == 1
    assert agent.state.initial_tax_rate == 1
    assert agent.state.final_tax_rate == 33
    assert len(agent.state.conditions) == 2
    assert agent.state.boundaries["developer"]["noProject"]["low"] == 200000


def test_players_known_event(agent):
    event = {
        "type": "event",
        "eventType": "players-known",
        "data": {
            "players": [
                {"number": 1, "role": 3, "tag": "Owner 1"},
                {"number": 2, "role": 2, "tag": "Developer"},
                {"number": 3, "role": 3, "tag": "Owner 2"},
                {"number": 4, "role": 3, "tag": "Owner 3"},
                {"number": 5, "role": 3, "tag": "Owner 4"},
                {"number": 6, "role": 1, "tag": "Speculator 1"},
            ]
        },
    }
    agent.update_state(event)
    assert len(agent.state.players) == 6
    assert agent.state.players[0]["number"] == 1
    assert agent.state.players[0]["role"] == 3
    assert agent.state.players[5]["tag"] == "Speculator 1"


def test_phase_transition_event(agent):
    event = {"type": "event", "eventType": "phase-transition", "data": {"round": 1, "phase": 6}}
    agent.update_state(event)
    assert agent.state.phase == 6


def test_value_signals_event(agent):
    event = {
        "type": "event",
        "eventType": "value-signals",
        "data": {"signals": [10225, 6363, 0], "publicSignal": [5837.759400000001, 0, 0], "condition": 0, "taxRate": 33},
    }
    agent.update_state(event)
    assert agent.state.value_signals == [10225, 6363, 0]
    assert agent.state.public_signal == [5837.759400000001, 0, 0]
    assert agent.state.winning_condition == 0
    assert agent.state.tax_rate == 33


def test_declarations_published_event(agent):
    event = {
        "type": "event",
        "eventType": "declarations-published",
        "data": {
            "declarations": [
                {
                    "id": 1,
                    "name": "Socialist Marten Lot",
                    "owner": "Coffee",
                    "role": 3,
                    "number": 1,
                    "d": [503117, 164567, 0],
                    "available": [True, True, True],
                },
                {
                    "id": 2,
                    "name": "Socialist Marten Lot",
                    "owner": "Coffee",
                    "role": 3,
                    "number": 2,
                    "d": [503117, 164567, 0],
                    "available": [True, True, True],
                },
            ],
            "winningCondition": 0,
        },
    }
    agent.update_state(event)
    assert len(agent.state.declarations) == 2
    assert agent.state.declarations[0]["id"] == 1
    assert agent.state.declarations[0]["name"] == "Socialist Marten Lot"
    assert agent.state.winning_condition == 0


@pytest.mark.asyncio
async def test_handle_phase(game_sequence_speculator, agent):
    for event in game_sequence_speculator:
        agent.update_state(event)
        if agent.state.phase == 3:
            result = await agent.handle_phase(3)
            break
    assert result
