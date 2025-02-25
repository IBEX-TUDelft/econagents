from abc import abstractmethod
from typing import Any, Callable, Optional, Protocol, Type, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from econagents.core.events import Message
from econagents.core.state.fields import EventField

EventHandler = Callable[[str, dict[str, Any]], None]
T = TypeVar("T", bound="GameState")


class PropertyMapping(BaseModel):
    """Mapping between event data and state properties

    Args:
        event_key: Key in the event data
        state_key: Key in the state object
        state_type: Whether to update private or public information ("private" or "public")
        phases: Optional list of phases where this mapping should be applied. If None, applies to all phases.
        exclude_phases: Optional list of phases where this mapping should not be applied.
                      Cannot be used together with phases.
    """

    event_key: str
    state_key: str
    state_type: str = "private"
    events: list[str] | None = None
    exclude_events: list[str] | None = None

    def model_post_init(self, __context: Any) -> None:
        """Validate that events and exclude_events are not both specified"""
        if self.events is not None and self.exclude_events is not None:
            raise ValueError("Cannot specify both events and exclude_events")

    def should_apply_in_event(self, current_event: str) -> bool:
        """Determine if this mapping should be applied in the current event"""
        if self.events is not None:
            return current_event in self.events
        if self.exclude_events is not None:
            return current_event not in self.exclude_events
        return True


class PrivateInformation(BaseModel):
    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=False)


class PublicInformation(BaseModel):
    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=False)


class MetaInformation(BaseModel):
    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=False)

    player_name: Optional[str] = EventField(default=None)
    player_number: Optional[int] = EventField(default=None)
    players: list[dict[str, Any]] = EventField(default_factory=list)
    phase: int = EventField(default=0)


class GameStateProtocol(Protocol):
    meta: MetaInformation
    private_information: PrivateInformation
    public_information: PublicInformation

    def model_dump(self) -> dict[str, Any]: ...

    def model_dump_json(self) -> str: ...


class GameState(BaseModel):
    meta: MetaInformation = EventField(default_factory=MetaInformation)
    private_information: PrivateInformation = EventField(default_factory=PrivateInformation)
    public_information: PublicInformation = EventField(default_factory=PublicInformation)

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        self._property_mappings = self._get_property_mappings()

    def update(self, event: Message) -> None:
        """
        Generic state update method that handles both property mappings and custom event handlers.

        Args:
            event: The event message containing event_type and data

        This method will:
        1. Check for custom event handlers first
        2. Fall back to property mappings if no custom handler exists
        3. Update state based on property mappings, considering phase restrictions
        """
        # Get custom event handlers from child class
        custom_handlers = self.get_custom_handlers()

        # Check if there's a custom handler for this event type
        if event.event_type in custom_handlers:
            custom_handlers[event.event_type](event.event_type, event.data)
            return

        # Update state based on mappings
        for mapping in self._property_mappings:
            # Skip if mapping shouldn't be applied in current event
            if not mapping.should_apply_in_event(event.event_type):
                continue

            # Skip if the event key isn't in the event data
            if mapping.event_key not in event.data:
                continue

            value = event.data[mapping.event_key]

            # Update the appropriate state object based on state_type
            if mapping.state_type == "meta":
                setattr(self.meta, mapping.state_key, value)
            elif mapping.state_type == "private":
                setattr(self.private_information, mapping.state_key, value)
            elif mapping.state_type == "public":
                setattr(self.public_information, mapping.state_key, value)

    def _get_property_mappings(self) -> list[PropertyMapping]:
        """
        Default implementation that generates property mappings from EventField metadata.

        Returns:
            List of PropertyMapping objects generated from field metadata.
        """
        mappings = []

        # Generate mappings from meta information fields
        mappings.extend(self._generate_mappings_from_model(self.meta.__class__, "meta"))

        # Generate mappings from private information fields
        mappings.extend(self._generate_mappings_from_model(self.private_information.__class__, "private"))

        # Generate mappings from public information fields
        mappings.extend(self._generate_mappings_from_model(self.public_information.__class__, "public"))

        return mappings

    def _generate_mappings_from_model(self, model_class: Type, state_type: str) -> list[PropertyMapping]:
        """
        Generate property mappings from a Pydantic model class.

        Args:
            model_class: The Pydantic model class to inspect
            state_type: The state type ("meta", "private", or "public")

        Returns:
            List of PropertyMapping objects
        """
        mappings = []

        for field_name, field_info in model_class.model_fields.items():
            # Skip fields with exclude_from_mapping=True
            exclude_from_mapping = False
            if hasattr(field_info, "json_schema_extra") and "event_metadata" in field_info.json_schema_extra:
                exclude_from_mapping = field_info.json_schema_extra["event_metadata"]["exclude_from_mapping"]
            elif hasattr(field_info, "exclude_from_mapping"):  # For backward compatibility
                exclude_from_mapping = field_info.exclude_from_mapping

            if exclude_from_mapping:
                continue

            # Get event key from event_key if provided, otherwise convert to camelCase
            event_key = None
            if hasattr(field_info, "json_schema_extra") and "event_metadata" in field_info.json_schema_extra:
                event_key = field_info.json_schema_extra["event_metadata"]["event_key"]
            elif hasattr(field_info, "event_key"):  # For backward compatibility
                event_key = field_info.event_key

            if event_key is None:
                # Convert snake_case to camelCase
                parts = field_name.split("_")
                event_key = parts[0] + "".join(x.title() for x in parts[1:])

            # Get events and exclude_events if provided
            events = None
            exclude_events = None

            if hasattr(field_info, "json_schema_extra") and "event_metadata" in field_info.json_schema_extra:
                events = field_info.json_schema_extra["event_metadata"]["events"]
                exclude_events = field_info.json_schema_extra["event_metadata"]["exclude_events"]
            else:
                # For backward compatibility
                events = getattr(field_info, "events", None)
                exclude_events = getattr(field_info, "exclude_events", None)

            mappings.append(
                PropertyMapping(
                    event_key=event_key,
                    state_key=field_name,
                    state_type=state_type,
                    events=events,
                    exclude_events=exclude_events,
                )
            )

        return mappings

    def get_custom_handlers(self) -> dict[str, EventHandler]:
        """
        Override this method to provide custom event handlers.
        Returns a mapping of event types to handler functions.
        """
        return {}
