#!/usr/bin/env python3
"""
Test script to verify IbexTudelftConfigParser can create state classes with MarketState.
"""

import sys
import yaml
from pathlib import Path
from econagents_ibex_tudelft import IbexTudelftConfigParser, MarketState

def test_market_state_creation():
    """Test creating a state class with MarketState field."""
    
    # Create a test configuration with MarketState
    config_dict = {
        "name": "Test Market Experiment",
        "description": "Test experiment with MarketState",
        "agent_roles": [
            {
                "role_id": 1,
                "name": "Trader",
                "llm_type": "ChatOpenAI",
                "llm_params": {"model": "gpt-4"},
            }
        ],
        "agents": [{"id": 1, "role_id": 1}],
        "state": {
            "meta_information": [
                {"name": "game_id", "type": "int", "default": 0},
                {"name": "phase", "type": "int", "default": 0},
            ],
            "public_information": [
                {"name": "market", "type": "MarketState", "default_factory": "MarketState"},
                {"name": "winning_condition", "type": "str", "default": ""},
                {"name": "round_limit", "type": "int", "default": 10},
            ],
            "private_information": [
                {"name": "wallet", "type": "dict", "default_factory": "dict"},
                {"name": "score", "type": "int", "default": 0},
            ],
        },
        "manager": {"type": "TurnBasedPhaseManager"},
        "runner": {
            "type": "TurnBasedGameRunner",
            "hostname": "localhost",
            "port": 8765,
            "path": "ws",
            "game_id": 1000,
        },
    }
    
    # Write config to a temporary file
    config_file = Path("test_config.yaml")
    with open(config_file, "w") as f:
        yaml.dump(config_dict, f)
    
    try:
        # Create parser and load config
        parser = IbexTudelftConfigParser(config_file)
        
        # Create state class
        StateClass = parser.create_state_class()
        
        # Create an instance
        state = StateClass()
        
        # Verify MarketState field exists and is properly initialized
        assert hasattr(state.public_information, 'market'), "Market field not found in public_information"
        assert isinstance(state.public_information.market, MarketState), f"Market field is not MarketState, got {type(state.public_information.market)}"
        
        # Test MarketState functionality
        order_data = {
            "id": 1,
            "sender": 100,
            "price": 50.0,
            "quantity": 10.0,
            "type": "bid",
            "condition": 1,
            "now": False
        }
        
        state.public_information.market.process_event("add-order", {"order": order_data})
        assert 1 in state.public_information.market.orders, "Order was not added to market"
        assert state.public_information.market.orders[1].price == 50.0, "Order price mismatch"
        
        print("✅ All tests passed!")
        print(f"  - State class created: {StateClass.__name__}")
        print(f"  - MarketState field initialized: {type(state.public_information.market)}")
        print(f"  - MarketState functionality working: order added successfully")
        
    finally:
        # Clean up
        if config_file.exists():
            config_file.unlink()

if __name__ == "__main__":
    try:
        test_market_state_creation()
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)