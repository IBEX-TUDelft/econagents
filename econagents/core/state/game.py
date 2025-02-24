from abc import abstractmethod
from typing import Any, Callable, Optional, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from econagents.core.events import Message

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
    phases: list[int] | None = None
    exclude_phases: list[int] | None = None

    def model_post_init(self, __context: Any) -> None:
        """Validate that phases and exclude_phases are not both specified"""
        if self.phases is not None and self.exclude_phases is not None:
            raise ValueError("Cannot specify both phases and exclude_phases")

    def should_apply_in_phase(self, current_phase: int) -> bool:
        """Determine if this mapping should be applied in the current phase"""
        if self.phases is not None:
            return current_phase in self.phases
        if self.exclude_phases is not None:
            return current_phase not in self.exclude_phases
        return True


class PrivateInformation(BaseModel):
    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=False)


class PublicInformation(BaseModel):
    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=False)


class MetaInformation(BaseModel):
    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=False)

    player_name: Optional[str] = None
    player_number: Optional[int] = None
    players: list[dict[str, Any]] = Field(default_factory=list)
    phase: int = Field(default=0)


class GameStateProtocol(Protocol):
    meta: MetaInformation
    private_information: PrivateInformation
    public_information: PublicInformation

    def model_dump(self) -> dict[str, Any]: ...

    def model_dump_json(self) -> str: ...


class GameState(BaseModel):
    meta: MetaInformation = Field(default_factory=MetaInformation)

    private_information: PrivateInformation = Field(default_factory=PrivateInformation)
    public_information: PublicInformation = Field(default_factory=PublicInformation)

    def update_state(self, event: Message) -> None:
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

        # Get property mappings from child class
        property_maps = self.get_property_mappings()

        # Update state based on mappings
        for mapping in property_maps:
            # Skip if mapping shouldn't be applied in current phase
            if not mapping.should_apply_in_phase(self.meta.phase):
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

    @abstractmethod
    def get_property_mappings(self) -> list[PropertyMapping]:
        """
        Override this method to provide property mappings.
        Returns a list of PropertyMapping objects.
        """
        return []

    def get_custom_handlers(self) -> dict[str, EventHandler]:
        """
        Override this method to provide custom event handlers.
        Returns a mapping of event types to handler functions.
        """
        return {}
