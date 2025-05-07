import pytest
import yaml
from pathlib import Path
from typing import Optional, List, Dict, Any
from unittest.mock import patch, AsyncMock

from pydantic import ValidationError

from econagents.config_parser.base import BaseConfigParser, ExperimentConfig, StateConfig
from econagents.config_parser.ibex_tudelft import IbexTudelftConfigParser
from econagents.core.state.game import GameState, MetaInformation, PrivateInformation, PublicInformation
from econagents.core.state.market import MarketState
from econagents.core.events import Message


@pytest.fixture
def sample_config_dict() -> Dict[str, Any]:
    """Provides a sample configuration dictionary."""
    return {
        "name": "Test Experiment",
        "description": "A test experiment configuration.",
        "agent_roles": [
            {
                "role_id": 1,
                "name": "TestRole",
                "llm_type": "ChatOpenAI",
                "llm_params": {"model_name": "gpt-test"},
            }
        ],
        "agents": [{"id": 1, "role_id": 1}],
        "state": {
            "meta_information": [
                {"name": "game_id", "type": "int", "default": 0},
                {"name": "phase", "type": "int", "default": 0},
                {"name": "player_name", "type": "str", "optional": True},
                {"name": "player_number", "type": "int", "optional": True},
                {"name": "players", "type": "list[dict[str, Any]]", "default_factory": "list"},
                {"name": "optional_meta", "type": "str", "optional": True, "default": None},
            ],
            "private_information": [
                {"name": "score", "type": "int", "default": 0},
                {"name": "secret_code", "type": "str", "optional": True},
            ],
            "public_information": [
                {"name": "round_limit", "type": "int", "default": 10},
                {"name": "description", "type": "str", "default": "Game"},
                {"name": "optional_public", "type": "float", "optional": True, "default": 3.14},
                {"name": "complex_optional", "type": "list[str]", "optional": True, "default_factory": "list"},
            ],
        },
        "manager": {"type": "TurnBasedPhaseManager"},
        "runner": {
            "type": "TurnBasedGameRunner",
            "hostname": "localhost",
            "port": 8765,
            "path": "ws",
            "game_id": 999,
        },
    }


@pytest.fixture
def config_file(tmp_path: Path, sample_config_dict: Dict[str, Any]) -> Path:
    """Creates a temporary YAML config file."""
    config_path = tmp_path / "test_config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(sample_config_dict, f)
    return config_path


@pytest.fixture
def market_state_config_dict() -> Dict[str, Any]:
    """Provides a sample configuration dictionary with a MarketState field."""
    return {
        "name": "MarketState Experiment",
        "agent_roles": [
            {
                "role_id": 1,
                "name": "MarketAgent",
                "llm_type": "ChatOpenAI",
            }
        ],
        "agents": [{"id": 1, "role_id": 1}],
        "state": {
            "public_information": [
                {"name": "current_market", "type": "MarketState", "default_factory": "MarketState"},
                {"name": "winning_condition", "type": "int", "optional": False, "default": 0},
            ],
            "private_information": [
                {"name": "wallet", "type": "list[dict[str, Any]]", "optional": False, "default": []},
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


@pytest.fixture
def market_state_config_file(tmp_path: Path, market_state_config_dict: Dict[str, Any]) -> Path:
    """Creates a temporary YAML config file with MarketState."""
    config_path = tmp_path / "market_state_config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(market_state_config_dict, f)
    return config_path


class TestBaseConfigParser:
    """Tests for the BaseConfigParser class."""

    def test_load_config(self, config_file: Path):
        """Test loading a valid configuration file."""
        parser = BaseConfigParser(config_path=config_file)
        assert isinstance(parser.config, ExperimentConfig)
        assert parser.config.name == "Test Experiment"
        assert len(parser.config.agent_roles) == 1
        assert len(parser.config.agents) == 1
        assert isinstance(parser.config.state, StateConfig)

    def test_create_state_class_basic(self, config_file: Path):
        """Test creating the dynamic GameState class."""
        parser = BaseConfigParser(config_path=config_file)
        state_class = parser.config.state.create_state_class()

        assert issubclass(state_class, GameState)
        assert state_class.__name__ == "DynamicGameState"

        # Check if components are subclasses of base Pydantic models
        assert issubclass(state_class.model_fields["meta"].annotation, MetaInformation)  # type: ignore
        assert issubclass(state_class.model_fields["private_information"].annotation, PrivateInformation)  # type: ignore
        assert issubclass(state_class.model_fields["public_information"].annotation, PublicInformation)  # type: ignore

    def test_dynamic_state_instantiation_and_defaults(self, config_file: Path):
        """Test instantiating the dynamic GameState class and check defaults."""
        parser = BaseConfigParser(config_path=config_file)
        DynamicGameState = parser.config.state.create_state_class()

        # Instantiate without arguments, should use defaults
        state_instance = DynamicGameState()

        # Check MetaInformation defaults
        assert state_instance.meta.game_id == 0
        assert state_instance.meta.phase == 0
        assert state_instance.meta.optional_meta is None  # type: ignore

        # Check PrivateInformation defaults
        assert state_instance.private_information.score == 0  # type: ignore
        assert state_instance.private_information.secret_code is None  # type: ignore

        # Check PublicInformation defaults
        assert state_instance.public_information.round_limit == 10  # type: ignore
        assert state_instance.public_information.description == "Game"  # type: ignore
        assert state_instance.public_information.optional_public == 3.14  # type: ignore # Optional with default
        assert state_instance.public_information.complex_optional == []  # type: ignore # Optional with default_factory

    def test_dynamic_state_instantiation_with_values(self, config_file: Path):
        """Test instantiating the dynamic GameState class with specific values."""
        parser = BaseConfigParser(config_path=config_file)
        DynamicGameState = parser.config.state.create_state_class()

        # Instantiate with specific values
        state_instance = DynamicGameState(
            meta={"game_id": 1, "phase": 2, "optional_meta": "meta_value"},
            private_information={"score": 100, "secret_code": "xyz"},
            public_information={
                "round_limit": 5,
                "description": "New Game",
                "optional_public": None,
                "complex_optional": ["a", "b"],
            },
        )

        # Check MetaInformation values
        assert state_instance.meta.game_id == 1
        assert state_instance.meta.phase == 2
        assert state_instance.meta.optional_meta == "meta_value"  # type: ignore

        # Check PrivateInformation values
        assert state_instance.private_information.score == 100  # type: ignore
        assert state_instance.private_information.secret_code == "xyz"  # type: ignore

        # Check PublicInformation values
        assert state_instance.public_information.round_limit == 5  # type: ignore
        assert state_instance.public_information.description == "New Game"  # type: ignore
        assert state_instance.public_information.optional_public is None  # type: ignore # Optional set to None
        assert state_instance.public_information.complex_optional == ["a", "b"]  # type: ignore

    def test_dynamic_state_validation(self, config_file: Path):
        """Test Pydantic validation for the dynamic GameState class."""
        parser = BaseConfigParser(config_path=config_file)
        DynamicGameState = parser.config.state.create_state_class()

        # Valid instantiation
        DynamicGameState(private_information={"score": 50})  # score is int, ok
        DynamicGameState(private_information={"secret_code": "abc"})  # secret_code is Optional[str], ok
        DynamicGameState(private_information={"secret_code": None})  # secret_code is Optional[str], None ok

        # Invalid instantiation (wrong type)
        with pytest.raises(ValidationError):
            DynamicGameState(private_information={"score": "not_an_int"})

        with pytest.raises(ValidationError):
            DynamicGameState(private_information={"secret_code": 123})  # Expected Optional[str]

        with pytest.raises(ValidationError):
            DynamicGameState(public_information={"complex_optional": "not_a_list"})  # Expected Optional[list[str]]

    def test_dynamic_state_update_optional_fields(self, config_file: Path):
        """Test updating optional fields in the dynamic GameState."""
        parser = BaseConfigParser(config_path=config_file)
        DynamicGameState = parser.config.state.create_state_class()
        state_instance = DynamicGameState()

        # Initially optional fields are None or default
        assert state_instance.meta.optional_meta is None  # type: ignore
        assert state_instance.private_information.secret_code is None  # type: ignore
        assert state_instance.public_information.optional_public == 3.14  # type: ignore
        assert state_instance.public_information.complex_optional == []  # type: ignore

        # Event to update optional fields
        event_data = {
            "optional_meta": "new_meta",
            "secret_code": "new_code",
            "optional_public": 1.23,
            "complex_optional": ["x", "y", "z"],
        }
        event = Message(message_type="event", event_type="update_optionals", data=event_data)
        state_instance.update(event)

        # Check updated values
        assert state_instance.meta.optional_meta == "new_meta"  # type: ignore
        assert state_instance.private_information.secret_code == "new_code"  # type: ignore
        assert state_instance.public_information.optional_public == 1.23  # type: ignore
        assert state_instance.public_information.complex_optional == ["x", "y", "z"]  # type: ignore

        # Event to set optional fields back to None (or default if applicable)
        event_data_reset = {
            "optional_meta": None,
            "secret_code": None,
            "optional_public": None,
            "complex_optional": None,  # Assuming None is acceptable for Optional[list[str]]
        }
        event_reset = Message(message_type="event", event_type="reset_optionals", data=event_data_reset)
        state_instance.update(event_reset)

        assert state_instance.meta.optional_meta is None  # type: ignore
        assert state_instance.private_information.secret_code is None  # type: ignore
        assert state_instance.public_information.optional_public is None  # type: ignore
        assert state_instance.public_information.complex_optional is None  # type: ignore

    def test_backward_compatibility_old_agent_format(self, tmp_path: Path):
        """Test loading config with the old 'agents' list containing role definitions."""
        old_config_dict = {
            "name": "Old Format Test",
            "agents": [  # Old format: role definitions are directly under 'agents'
                {
                    "role_id": 1,
                    "name": "OldRole",
                    "llm_type": "ChatOpenAI",
                    "llm_params": {"model_name": "gpt-old"},
                }
            ],
            # No 'agent_roles' key
            "state": {"meta_information": [{"name": "game_id", "type": "int"}]},
            "manager": {"type": "TurnBasedPhaseManager"},
            "runner": {
                "type": "TurnBasedGameRunner",
                "hostname": "localhost",
                "port": 8765,
                "path": "ws",
                "game_id": 111,
            },
        }
        config_path = tmp_path / "old_config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(old_config_dict, f)

        parser = BaseConfigParser(config_path=config_path)
        assert isinstance(parser.config, ExperimentConfig)
        assert parser.config.name == "Old Format Test"

        # Check that 'agents' from the old format were moved to 'agent_roles'
        assert len(parser.config.agent_roles) == 1
        assert parser.config.agent_roles[0].name == "OldRole"
        assert parser.config.agent_roles[0].role_id == 1

        # Check that 'agents' (the mapping list) is now empty
        assert len(parser.config.agents) == 0

    def test_type_resolution_complex(self, tmp_path: Path):
        """Test resolving complex types like list[str]."""
        complex_type_config = {
            "name": "Complex Type Test",
            "agent_roles": [],
            "agents": [],
            "state": {
                "public_information": [
                    {"name": "string_list", "type": "list[str]", "default_factory": "list"},
                    {"name": "optional_int_list", "type": "list[int]", "optional": True},
                ]
            },
            "manager": {"type": "TurnBasedPhaseManager"},
            "runner": {
                "type": "TurnBasedGameRunner",
                "hostname": "localhost",
                "port": 1234,
                "path": "ws",
                "game_id": 1,
            },
        }
        config_path = tmp_path / "complex_config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(complex_type_config, f)

        parser = BaseConfigParser(config_path=config_path)
        DynamicGameState = parser.config.state.create_state_class()
        state_instance = DynamicGameState()

        assert state_instance.public_information.string_list == []  # type: ignore
        assert state_instance.public_information.optional_int_list is None  # type: ignore

        # Test valid assignment
        state_instance.public_information.string_list = ["a", "b"]  # type: ignore
        state_instance.public_information.optional_int_list = [1, 2, 3]  # type: ignore
        assert state_instance.public_information.string_list == ["a", "b"]  # type: ignore
        assert state_instance.public_information.optional_int_list == [1, 2, 3]  # type: ignore

        with pytest.raises(ValidationError):
            DynamicGameState(public_information={"string_list": [1, 2]})  # list[int] instead of list[str]

        with pytest.raises(ValidationError):
            DynamicGameState(public_information={"optional_int_list": ["a", "b"]})  # list[str] instead of list[int]


@pytest.mark.asyncio
class TestIbexTudelftConfigParser:
    def test_dynamic_state_with_market_state(self, market_state_config_file: Path):
        """Test creating and instantiating a dynamic GameState with a MarketState field."""
        parser = IbexTudelftConfigParser(config_path=market_state_config_file)
        DynamicGameState = parser.config.state.create_state_class()

        # Check the field type in the generated model
        assert "current_market" in DynamicGameState.model_fields["public_information"].annotation.model_fields  # type: ignore
        assert (
            DynamicGameState.model_fields["public_information"].annotation.model_fields["current_market"].annotation  # type: ignore
            == MarketState
        )

        # Instantiate the state
        state_instance = DynamicGameState()

        # Verify the field is initialized correctly using the default factory
        assert isinstance(state_instance.public_information.current_market, MarketState)  # type: ignore
        assert state_instance.public_information.current_market.orders == {}  # type: ignore
        assert state_instance.public_information.current_market.trades == []  # type: ignore

        order_data = {
            "id": 1,
            "sender": 1,
            "price": 10.0,
            "quantity": 5.0,
            "type": "bid",
            "condition": 0,
        }
        state_instance.public_information.current_market.process_event("add-order", {"order": order_data})  # type: ignore

        assert 1 in state_instance.public_information.current_market.orders  # type: ignore
        assert state_instance.public_information.current_market.orders[1].price == 10.0  # type: ignore

    async def test_run_experiment(self, market_state_config_file: Path):
        """
        Test that run_experiment correctly prepares and uses an enhanced state class
        with MarketState when MarketState is defined in the configuration.
        It mocks GameRunner.run_game to isolate the test to the setup phase.
        """
        parser = IbexTudelftConfigParser(config_path=market_state_config_file)

        # Prepare inputs for run_experiment
        # Based on market_state_config_dict: agents: [{"id": 1, "role_id": 1}]
        login_payloads = [{"agent_id": 1, "auth_token": "test_token"}]
        game_id = 123

        with patch("econagents.config_parser.ibex_tudelft.GameRunner") as mock_game_runner_class:
            # Configure the mock for run_game to be an AsyncMock
            mock_game_runner_instance = mock_game_runner_class.return_value
            mock_game_runner_instance.run_game = AsyncMock()

            # Call the method under test
            await parser.run_experiment(login_payloads=login_payloads, game_id=game_id)

            # Assertions
            # 1. Check if GameRunner was instantiated
            mock_game_runner_class.assert_called_once()

            # 2. Get the arguments passed to GameRunner constructor
            args, kwargs = mock_game_runner_class.call_args
            runner_config_arg = kwargs.get("config")
            assert runner_config_arg is not None, "GameRunner was not called with a 'config' keyword argument."

            # 3. Verify the state_class in the runner's config
            assert runner_config_arg.state_class is not None, "state_class in runner_config was not set."

            DynamicGameStateWithMarket = runner_config_arg.state_class

            # 4. Check if the state_class is correctly formed (has MarketState)
            assert "public_information" in DynamicGameStateWithMarket.model_fields
            public_info_model = DynamicGameStateWithMarket.model_fields["public_information"].annotation

            assert "current_market" in public_info_model.model_fields
            assert public_info_model.model_fields["current_market"].annotation == MarketState

            state_instance = DynamicGameStateWithMarket()

            event_data = {"wallet": [{"balance": 0, "shares": 0}, {"balance": 0, "shares": 0}]}
            state_instance.update(Message(message_type="event", event_type="update_wallet", data=event_data))  # type: ignore
            assert state_instance.private_information.wallet == [
                {"balance": 0, "shares": 0},
                {"balance": 0, "shares": 0},
            ]

            # Add an order
            order_data = {
                "id": 1,
                "sender": 1,
                "price": 10.0,
                "quantity": 5.0,
                "type": "bid",
                "condition": 0,
            }
            state_instance.update(Message(message_type="event", event_type="add-order", data={"order": order_data}))  # type: ignore
            assert 1 in state_instance.public_information.current_market.orders  # type: ignore
            assert state_instance.public_information.current_market.orders[1].price == 10.0  # type: ignore

            order_data = {
                "id": 1,
                "sender": 1,
                "price": 10.0,
                "quantity": 5.0,
                "type": "ask",
            }
            state_instance.update(
                Message(
                    message_type="event",
                    event_type="asset-movement",
                    data={"balance": 100, "shares": 10},
                )
            )  # type: ignore
            assert state_instance.private_information.wallet[0]["balance"] == 100  # type: ignore
            assert state_instance.private_information.wallet[0]["shares"] == 10  # type: ignore

            # 5. Verify game_id was passed correctly
            assert runner_config_arg.game_id == game_id

            # 6. Verify run_game was called
            mock_game_runner_instance.run_game.assert_awaited_once()
