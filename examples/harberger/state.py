from typing import Any, Optional

from pydantic import Field, computed_field

from econagents.core.state.fields import EventField
from econagents.core.state.game import EventHandler, GameState, MetaInformation, PrivateInformation, PublicInformation
from econagents.core.state.market import MarketState

# EventField lets you specify the event key of the event data in the message
# event_key is the key of the event data in the message. If not specified, the event key is the field name.
# exclude_from_mapping is used to exclude the field from the mapping of the event data, so it is not updated when an event is processed
# exclude_events is used to exclude the field from the events that trigger an update, so it is not updated when an event is processed
# events are the events that trigger an update, if not specified, all events will trigger an update if they have the event key


class HLMeta(MetaInformation):
    # These fields are required in MetaInformation
    game_id: int = EventField(default=0, exclude_from_mapping=True)
    player_name: Optional[str] = EventField(default=None, event_key="name")
    player_number: Optional[int] = EventField(default=None, event_key="number")
    players: list[dict[str, Any]] = EventField(default_factory=list, event_key="players")
    phase: int = EventField(default=0, event_key="phase")


class HLPrivate(PrivateInformation):
    # PrivateInformation can have have any fields
    wallet: list[dict[str, Any]] = EventField(default_factory=list)
    value_signals: list[float] = EventField(default_factory=list, event_key="signals")
    declarations: list[dict[str, Any]] = EventField(default_factory=list)
    property: dict[str, Any] = EventField(default_factory=dict, exclude_events=["profit"])


class HLPublic(PublicInformation):
    # PublicInformation can have any fields
    # Tax
    tax_rate: float = EventField(default=0, event_key="taxRate")
    initial_tax_rate: float = EventField(default=0, event_key="initialTaxRate")
    final_tax_rate: float = EventField(default=0, event_key="finalTaxRate")

    # Boundaries and conditions
    boundaries: dict[str, Any] = EventField(default_factory=dict)
    conditions: list[dict[str, Any]] = EventField(default_factory=list)

    # Market
    value_signals: list[float] = EventField(default_factory=list, event_key="signals")
    market_state: MarketState = EventField(default_factory=MarketState)
    public_signal: list[float] = EventField(default_factory=list, event_key="publicSignal")

    # Winning condition
    winning_condition: int = EventField(default=0, event_key="winningCondition")

    @computed_field
    def winning_condition_description(self) -> dict[str, Any]:
        return self.conditions[self.winning_condition] if self.conditions else {}


class HLGameState(GameState):
    meta: HLMeta = Field(default_factory=HLMeta)
    private_information: HLPrivate = Field(default_factory=HLPrivate)
    public_information: HLPublic = Field(default_factory=HLPublic)

    # This is needed because the game_id is not in the event data
    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        self.meta.game_id = kwargs.get("game_id", 0)

    # This is needed to build the order book
    def get_custom_handlers(self) -> dict[str, EventHandler]:
        """Provide custom event handlers for market events"""
        market_events = ["add-order", "update-order", "delete-order", "contract-fulfilled", "asset-movement"]
        return {event: self._handle_market_event for event in market_events}

    # This is needed to build the order book
    def _handle_market_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Handle market-related events by delegating to MarketState"""
        self.public_information.market_state.process_event(event_type=event_type, data=data)

        if event_type == "asset-movement":
            winning_condition = self.public_information.winning_condition
            self.private_information.wallet[winning_condition]["balance"] = data["balance"]
            self.private_information.wallet[winning_condition]["shares"] = data["shares"]
