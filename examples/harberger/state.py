from typing import Any, Optional

from pydantic import Field

from econagents.core.state.fields import EventField
from econagents.core.state.game import EventHandler, GameState, MetaInformation, PrivateInformation, PublicInformation
from econagents.core.state.market import MarketState


class HarbergerMetaInformation(MetaInformation):
    player_name: Optional[str] = EventField(default=None, event_key="name")
    player_number: Optional[int] = EventField(default=None, event_key="number")
    players: list[dict[str, Any]] = EventField(default_factory=list, event_key="players")
    phase: int = EventField(default=0, event_key="phase")


class HarbergerPrivateInformation(PrivateInformation):
    wallet: list[dict[str, Any]] = EventField(default_factory=list)
    value_signals: list[float] = EventField(default_factory=list, event_key="signals")
    declarations: list[dict[str, Any]] = EventField(default_factory=list)
    property: dict[str, Any] = EventField(default_factory=dict, exclude_events=["profit"])


class HarbergerPublicInformation(PublicInformation):
    # Tax
    tax_rate: float = EventField(default=0, event_key="taxRate")
    initial_tax_rate: float = EventField(default=0, event_key="initialTaxRate")
    final_tax_rate: float = EventField(default=0, event_key="finalTaxRate")

    # Boundaries and conditions
    boundaries: dict[str, Any] = EventField(default_factory=dict)
    conditions: list[dict[str, Any]] = EventField(default_factory=list)

    # Market
    value_signals: list[float] = EventField(default_factory=list)
    market_state: MarketState = EventField(default_factory=MarketState)
    public_signal: list[float] = EventField(default_factory=list, event_key="publicSignal")

    # Winning condition
    winning_condition: int = EventField(default=0, event_key="winningCondition")

    @property
    def winning_condition_description(self) -> dict[str, Any]:
        return self.conditions[self.winning_condition]


class HarbergerGameState(GameState):
    meta: HarbergerMetaInformation = Field(default_factory=HarbergerMetaInformation)
    private_information: HarbergerPrivateInformation = Field(default_factory=HarbergerPrivateInformation)
    public_information: HarbergerPublicInformation = Field(default_factory=HarbergerPublicInformation)

    def __init__(self, game_id: int):
        super().__init__()
        self.meta.game_id = game_id

    def get_custom_handlers(self) -> dict[str, EventHandler]:
        """Provide custom event handlers for market events"""
        market_events = ["add-order", "update-order", "delete-order", "contract-fulfilled", "asset-movement"]
        return {event: self._handle_market_event for event in market_events}

    def _handle_market_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Handle market-related events by delegating to MarketState"""
        self.public_information.market_state.process_event(event_type=event_type, data=data)

        if event_type == "asset-movement":
            winning_condition = self.public_information.winning_condition
            self.private_information.wallet[winning_condition]["balance"] = data["balance"]
            self.private_information.wallet[winning_condition]["shares"] = data["shares"]
