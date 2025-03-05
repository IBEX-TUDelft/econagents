import json
import pytest
from typing import Any, Dict
from pydantic import Field

from econagents.core.events import Message
from econagents.core.state.fields import EventField
from econagents.core.state.game import (
    GameState,
    MetaInformation,
    PrivateInformation,
    PropertyMapping,
    PublicInformation,
)


class TestPropertyMapping:
    """Tests for PropertyMapping class."""

    def test_initialization(self):
        """Test basic initialization of PropertyMapping."""
        mapping = PropertyMapping(
            event_key="test_event_key",
            state_key="test_state_key",
            state_type="private",
        )

        assert mapping.event_key == "test_event_key"
        assert mapping.state_key == "test_state_key"
        assert mapping.state_type == "private"
        assert mapping.events is None
        assert mapping.exclude_events is None

    def test_initialization_with_both_event_lists(self):
        """Test that initialization with both events and exclude_events raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            PropertyMapping(
                event_key="test_event_key",
                state_key="test_state_key",
                state_type="private",
                events=["event1"],
                exclude_events=["event2"],
            )

        assert "Cannot specify both events and exclude_events" in str(exc_info.value)

    def test_should_apply_in_event_no_restrictions(self):
        """Test should_apply_in_event with no restrictions."""
        mapping = PropertyMapping(
            event_key="test_event_key",
            state_key="test_state_key",
        )

        assert mapping.should_apply_in_event("any_event") is True

    def test_should_apply_in_event_with_events(self):
        """Test should_apply_in_event with events list."""
        mapping = PropertyMapping(
            event_key="test_event_key",
            state_key="test_state_key",
            events=["event1", "event2"],
        )

        assert mapping.should_apply_in_event("event1") is True
        assert mapping.should_apply_in_event("event2") is True
        assert mapping.should_apply_in_event("event3") is False

    def test_should_apply_in_event_with_exclude_events(self):
        """Test should_apply_in_event with exclude_events list."""
        mapping = PropertyMapping(
            event_key="test_event_key",
            state_key="test_state_key",
            exclude_events=["event1", "event2"],
        )

        assert mapping.should_apply_in_event("event1") is False
        assert mapping.should_apply_in_event("event2") is False
        assert mapping.should_apply_in_event("event3") is True

    def test_get_property_mappings(self):
        """Test that _get_property_mappings returns a list of PropertyMapping objects."""
        state = GameState()
        mappings = state._get_property_mappings()

        assert isinstance(mappings, list)
        assert all(isinstance(mapping, PropertyMapping) for mapping in mappings)

        # Should have mappings for the default fields in MetaInformation
        meta_mappings = [m for m in mappings if m.state_type == "meta"]
        assert len(meta_mappings) > 0


class CustomGameState(GameState):
    """Custom GameState implementation for testing."""

    # Add custom_handler_called as a field so it can be set on an instance
    custom_handler_called: bool = Field(default=False)

    def get_custom_handlers(self) -> Dict[str, Any]:
        """Provide custom event handlers for testing."""

        def handle_custom_event(event_type: str, data: Dict[str, Any]) -> None:
            self.custom_handler_called = True
            self.meta.game_id = data.get("game_id", 0)

        return {"custom_event": handle_custom_event}


class TestGameState:
    """Tests for GameState class."""

    def test_initialization(self):
        """Test GameState initialization."""
        state = GameState()

        assert isinstance(state.meta, MetaInformation)
        assert isinstance(state.private_information, PrivateInformation)
        assert isinstance(state.public_information, PublicInformation)

    def test_initialization_with_values(self):
        """Test GameState initialization with values."""
        meta = MetaInformation(game_id=123, phase=2)
        private = PrivateInformation(cards=["card1", "card2"])
        public = PublicInformation(turn=3)

        state = GameState(
            meta=meta,
            private_information=private,
            public_information=public,
        )

        assert state.meta.game_id == 123
        assert state.meta.phase == 2
        assert state.private_information.cards == ["card1", "card2"]
        assert state.public_information.turn == 3

    def test_update_with_property_mapping(self):
        """Test updating state with property mappings."""
        state = GameState()

        # Create an event message with the correct msg_type field
        event = Message(
            message_type="test",
            event_type="update_phase",
            data={"phase": 3, "game_id": 456, "player_name": "test_player"},
        )

        # Update the state with the event
        state.update(event)

        # Verify that the state was updated correctly
        assert state.meta.phase == 3
        assert state.meta.game_id == 456
        assert state.meta.player_name == "test_player"

    def test_update_with_custom_handler(self):
        """Test updating state with custom event handler."""
        state = CustomGameState()

        # Create an event that should trigger the custom handler
        event = Message(message_type="test", event_type="custom_event", data={"game_id": 789})

        # Update the state with the event
        state.update(event)

        # Verify that the custom handler was called
        assert state.custom_handler_called is True
        assert state.meta.game_id == 789

    def test_update_with_missing_event_key(self):
        """Test update behavior when event key is missing from data."""
        state = GameState()

        # Initial values
        state.meta.phase = 1

        # Create an event with missing keys
        event = Message(
            message_type="test",
            event_type="update_phase",
            data={"some_other_key": "value"},  # Missing "phase" key
        )

        # Update should not change phase
        state.update(event)
        assert state.meta.phase == 1  # Should remain unchanged

    def test_update_with_event_filtering(self):
        """Test update with event filtering in PropertyMapping."""

        class FilteredPrivateInformation(PrivateInformation):
            test_value: str = EventField(default="initial", event_key="value", events=["specific_event"])

        class FilteredGameState(GameState):
            private_information: FilteredPrivateInformation = EventField(default_factory=FilteredPrivateInformation)

        state = FilteredGameState()

        # Event that should be filtered out
        event1 = Message(message_type="test", event_type="wrong_event", data={"value": "updated"})

        # Event that should be applied
        event2 = Message(message_type="test", event_type="specific_event", data={"value": "updated"})

        # First update should be filtered out
        state.update(event1)
        assert state.private_information.test_value == "initial"  # Unchanged

        # Second update should be applied
        state.update(event2)
        assert state.private_information.test_value == "updated"

    def test_model_dump(self):
        """Test model_dump method."""
        state = GameState()
        state.meta.game_id = 123
        state.meta.phase = 2
        state.private_information.cards = ["card1", "card2"]
        state.public_information.turn = 3

        dumped = state.model_dump()

        assert isinstance(dumped, dict)
        assert dumped["meta"]["game_id"] == 123
        assert dumped["meta"]["phase"] == 2
        assert dumped["private_information"]["cards"] == ["card1", "card2"]
        assert dumped["public_information"]["turn"] == 3

    def test_model_dump_json(self):
        """Test model_dump_json method."""
        state = GameState()
        state.meta.game_id = 123
        state.meta.phase = 2
        state.private_information.cards = ["card1", "card2"]
        state.public_information.turn = 3

        dumped_json = state.model_dump_json()

        # Verify it's valid JSON
        parsed = json.loads(dumped_json)
        assert isinstance(parsed, dict)
        assert parsed["meta"]["game_id"] == 123
        assert parsed["meta"]["phase"] == 2
        assert parsed["private_information"]["cards"] == ["card1", "card2"]
        assert parsed["public_information"]["turn"] == 3
