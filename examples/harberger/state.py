from typing import Any

from pydantic import Field

from econagents.core.state.game import EventHandler, GameState, PrivateInformation, PropertyMapping, PublicInformation
from econagents.core.state.market import MarketState
from examples.harberger.config import property_mappings


class HarbergerPrivateInformation(PrivateInformation):
    wallet: list[dict[str, Any]] = Field(default_factory=list)
    value_signals: list[float] = Field(default_factory=list)
    declarations: list[dict[str, Any]] = Field(default_factory=list)
    property: dict[str, Any] = Field(default_factory=dict)


class HarbergerPublicInformation(PublicInformation):
    # Tax
    tax_rate: float = 0
    initial_tax_rate: float = 0
    final_tax_rate: float = 0

    # Boundaries and conditions
    boundaries: dict[str, Any] = Field(default_factory=dict)
    conditions: list[dict[str, Any]] = Field(default_factory=list)

    # Market
    value_signals: list[float] = Field(default_factory=list)
    market_state: MarketState = Field(default_factory=MarketState)
    public_signal: list[float] = Field(default_factory=list)

    # Winning condition
    winning_condition: int = 0

    @property
    def winning_condition_description(self) -> dict[str, Any]:
        return self.conditions[self.winning_condition]


class HarbergerGameState(GameState):
    private_information: HarbergerPrivateInformation = Field(default_factory=HarbergerPrivateInformation)
    public_information: HarbergerPublicInformation = Field(default_factory=HarbergerPublicInformation)

    def get_property_mappings(self) -> list[PropertyMapping]:
        return property_mappings

    def get_custom_handlers(self) -> dict[str, EventHandler]:
        """Provide custom event handlers for market events"""
        market_events = ["add-order", "update-order", "delete-order", "contract-fulfilled", "asset-movement"]
        return {event: self._handle_market_event for event in market_events} | {"profit": self._handle_profit}

    def _handle_profit(self, event_type: str, data: dict[str, Any]) -> None:
        """Handle profit events"""
        pass

    def _handle_market_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Handle market-related events by delegating to MarketState"""
        self.public_information.market_state.process_event(event_type=event_type, data=data)

        if event_type == "asset-movement":
            winning_condition = self.public_information.winning_condition
            self.private_information.wallet[winning_condition]["balance"] = data["balance"]
            self.private_information.wallet[winning_condition]["shares"] = data["shares"]
