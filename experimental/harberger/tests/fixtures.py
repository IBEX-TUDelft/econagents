from typing import Any

import pytest


@pytest.fixture
def game_sequence_speculator() -> list[dict[str, Any]]:
    """Returns a complete sequence of game events in chronological order."""
    return [
        # Event 1: Name Assignment
        {"type": "event", "eventType": "assign-name", "data": {"name": "Red", "number": 6, "ruleset": "Harberger"}},
        # Event 2: Role Assignment
        {
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
                    "owner": {
                        "noProject": {"low": 350000, "high": 600000},
                        "projectA": {"low": 150000, "high": 350000},
                    },
                },
                "taxRate": 1,
                "initialTaxRate": 1,
                "finalTaxRate": 33,
                "conditions": [
                    {"name": "No Project", "id": 0, "parameter": "no_project", "key": "noProject"},
                    {"name": "Project", "id": 1, "parameter": "project_a", "key": "projectA"},
                ],
            },
        },
        # Event 3: Players Known
        {
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
        },
        # Event 4: Initial Phase Transitions
        {"type": "event", "eventType": "phase-transition", "data": {"round": 1, "phase": 1}},
        {"type": "event", "eventType": "phase-transition", "data": {"round": 1, "phase": 2}},
        # Event 5: First Declarations
        {
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
                        "name": "Native Ostrich Lot",
                        "owner": "Pink",
                        "role": 2,
                        "number": 2,
                        "d": [344731, 303978, 0],
                        "available": [True, True, True],
                    },
                    {
                        "id": 3,
                        "name": "Sophisticated Beetle Lot",
                        "owner": "Aquamarine",
                        "role": 3,
                        "number": 3,
                        "d": [379164, 262055, 0],
                        "available": [True, True, True],
                    },
                    {
                        "id": 4,
                        "name": "Excellent Mockingbird Lot",
                        "owner": "Black",
                        "role": 3,
                        "number": 4,
                        "d": [279964, 348666, 0],
                        "available": [True, True, True],
                    },
                    {
                        "id": 5,
                        "name": "Steep Jay Lot",
                        "owner": "Beige",
                        "role": 3,
                        "number": 5,
                        "d": [262042, 218218, 0],
                        "available": [True, True, True],
                    },
                ],
                "winningCondition": 0,
            },
        },
        # Event 6: Phase 3 - Value Signals
        {"type": "event", "eventType": "phase-transition", "data": {"round": 1, "phase": 3}},
        # Event 7: First Snipes
        {"type": "event", "eventType": "first-snipes", "data": {"snipes": []}},
        # Event 8: Value Signals
        {
            "type": "event",
            "eventType": "value-signals",
            "data": {
                "signals": [10225, 6363, 0],
                "publicSignal": [5837.759400000001, 0, 0],
                "condition": 0,
                "taxRate": 33,
            },
        },
        # Event 9: Trading Phase
        {"type": "event", "eventType": "phase-transition", "data": {"round": 1, "phase": 5}},
        {"type": "event", "eventType": "phase-transition", "data": {"round": 1, "phase": 6}},
        # Event 10: Market Order
        {
            "type": "event",
            "eventType": "add-order",
            "data": {"order": {"id": 1, "sender": 6, "price": 4694, "quantity": 1, "type": "ask", "condition": 0}},
        },
        # Event 11: Phase 7 and Final Declarations
        {"type": "event", "eventType": "phase-transition", "data": {"round": 1, "phase": 7}},
        {
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
                        "d": [254084, 218149, 0],
                        "available": [True, False, False],
                    },
                    {
                        "id": 2,
                        "name": "Native Ostrich Lot",
                        "owner": "Pink",
                        "role": 2,
                        "number": 2,
                        "d": [460597, 189713, 0],
                        "available": [True, False, False],
                    },
                    {
                        "id": 3,
                        "name": "Sophisticated Beetle Lot",
                        "owner": "Aquamarine",
                        "role": 3,
                        "number": 3,
                        "d": [442963, 298502, 0],
                        "available": [True, False, False],
                    },
                    {
                        "id": 4,
                        "name": "Excellent Mockingbird Lot",
                        "owner": "Black",
                        "role": 3,
                        "number": 4,
                        "d": [256582, 349748, 0],
                        "available": [True, False, False],
                    },
                    {
                        "id": 5,
                        "name": "Steep Jay Lot",
                        "owner": "Beige",
                        "role": 3,
                        "number": 5,
                        "d": [378424, 154261, 0],
                        "available": [True, False, False],
                    },
                ],
                "winningCondition": 0,
            },
        },
        # Event 12: Final Phases and Results
        {"type": "event", "eventType": "phase-transition", "data": {"round": 1, "phase": 8}},
        {"type": "event", "eventType": "phase-transition", "data": {"round": 1, "phase": 9}},
        # Event 13: Profits and Final Results
        {
            "type": "event",
            "eventType": "second-snipes",
            "data": {
                "snipes": [
                    {"player": {"number": 6, "role": 1}, "target": {"number": 1, "role": 3}, "profit": 165958},
                    {"player": {"number": 6, "role": 1}, "target": {"number": 2, "role": 2}, "profit": -37298.5},
                    {"player": {"number": 6, "role": 1}, "target": {"number": 3, "role": 3}, "profit": 19518.5},
                    {"player": {"number": 6, "role": 1}, "target": {"number": 4, "role": 3}, "profit": 151709},
                    {"player": {"number": 6, "role": 1}, "target": {"number": 5, "role": 3}, "profit": 100788},
                ]
            },
        },
        {"type": "event", "eventType": "final-price", "data": {"price": 5915.745, "winningCondition": 0}},
        {
            "type": "event",
            "eventType": "round-summary",
            "data": {
                "round": 1,
                "condition": 0,
                "firstRepurchase": 0,
                "snipes": [
                    {"player": {"number": 6, "role": 1}, "target": {"number": 1, "role": 3}, "profit": 165958},
                    {"player": {"number": 6, "role": 1}, "target": {"number": 2, "role": 2}, "profit": -37298.5},
                    {"player": {"number": 6, "role": 1}, "target": {"number": 3, "role": 3}, "profit": 19518.5},
                    {"player": {"number": 6, "role": 1}, "target": {"number": 4, "role": 3}, "profit": 151709},
                    {"player": {"number": 6, "role": 1}, "target": {"number": 5, "role": 3}, "profit": 100788},
                ],
                "market": {"balance": 50000, "shares": 5, "price": 5915.745},
                "secondRepurchase": 400675,
            },
        },
        # Event 14: Game Over
        {"type": "event", "eventType": "game-over", "data": {}},
    ]
