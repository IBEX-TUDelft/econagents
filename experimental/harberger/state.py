from typing import Any, Optional
from pydantic import BaseModel, Field

from experimental.harberger.models import Message, mappings


# SR: all interactions on the market are specific to the design of the market, and thus game specific. 


# SR: Most markets will have orders in both the aks/bid type, all have at least one of the two these could be reused by other market experiments
class Order(BaseModel):
    id: int
    sender: int
    price: float
    quantity: float
    type: str
    condition: int
    now: bool = False

# SR: all markets deal with transactions, those could be reused
class Trade(BaseModel):
    from_id: int
    to_id: int
    price: float
    quantity: float
    condition: int
    median: Optional[float] = None

# SR: Most markets will have an open orderbook, this could be reused
class MarketState(BaseModel):
    """
    Represents the current state of the market:
    - Active orders in an order book
    - History of recent trades
    """

    orders: dict[int, Order] = {}
    trades: list[Trade] = []

    def process_event(self, event_type: str, data: dict):
        """
        Update the MarketState based on the eventType and
        event data from the server.
        """
        if event_type == "add-order":
            self._on_add_order(data["order"])

        elif event_type == "update-order":
            self._on_update_order(data["order"])

        elif event_type == "delete-order":
            self._on_delete_order(data["order"])

        elif event_type == "contract-fulfilled":
            self._on_contract_fulfilled(data)

    def get_orders_from_player(self, player_id: int) -> list[Order]:
        """Get all orders from a specific player."""
        return [order for order in self.orders.values() if order.sender == player_id]

    def _on_add_order(self, order_data: dict):
        """
        The server is telling us a new order has been added.
        We'll store it in self.orders by ID.
        """
        order_id = order_data["id"]
        new_order = Order(
            id=order_id,
            sender=order_data["sender"],
            price=order_data["price"],
            quantity=order_data["quantity"],
            type=order_data["type"],
            condition=order_data["condition"],
            now=order_data.get("now", False),
        )
        self.orders[order_id] = new_order

    def _on_update_order(self, order_data: dict):
        """
        The server is telling us the order's quantity or other fields
        have changed (often due to partial fills).
        """
        order_id = order_data["id"]
        if order_id in self.orders:
            existing = self.orders[order_id]
            # For example, update quantity:
            existing.quantity = order_data.get("quantity", existing.quantity)
            # You could also update price if the server protocol allows it
            # existing.price = order_data.get("price", existing.price)
            # existing.type = order_data.get("type", existing.type)
            # etc.
            self.orders[order_id] = existing

    def _on_delete_order(self, order_data: dict):
        """
        The server is telling us this order is removed
        from the order book (fully filled or canceled).
        """
        order_id = order_data["id"]
        if order_id in self.orders:
            del self.orders[order_id]

    def _on_contract_fulfilled(self, data: dict):
        """
        This indicates a trade has happened between 'from' and 'to'.
        The server might also send update-order or delete-order events
        to reflect the fill on the order book.
        We track the trade in self.trades, but we typically rely
        on update-order or delete-order to fix the order's quantity.
        """
        new_trade = Trade(
            from_id=data["from"],
            to_id=data["to"],
            price=data["price"],
            quantity=data.get("quantity", 1.0),
            condition=data["condition"],
            median=data.get("median"),
        )
        self.trades.append(new_trade)

# SR: here we have a mix of general and game specific defintions
# SR: all games have a gamestate, or state of the world in the definition file, but the content of this game state is game specific
# SR: the same holds for its updating, game states and phases have to be updated in any game. What that means is game specific. 
class GameState(BaseModel):
    # Basic info, 
    # SR: this block has meta-information and process information that will be present in any experiment
    player_name: str = ""
    player_number: Optional[int] = None
    players: list[dict[str, Any]] = Field(default_factory=list)
    phase: int = 0

    # Wallet and market info, 
    wallet: dict[str, Any] = Field(default_factory=dict)    # SR: part of private information
    tax_rate: float = 0                                     # SR: part of public information
    initial_tax_rate: float = 0                             # SR: part of public information
    final_tax_rate: float = 0                               # SR: part of public information

    # Value boundaries and conditions
    boundaries: dict[str, Any] = Field(default_factory=dict)        # SR: part of public information
    conditions: list[dict[str, Any]] = Field(default_factory=list)  # SR: part of public information
    property: dict[str, Any] = Field(default_factory=dict)          # SR: part of ?  information

    # Market signals
    value_signals: list[float] = Field(default_factory=list)    # SR: part of private information
    public_signal: list[float] = Field(default_factory=list)    # SR: part of public information
    winning_condition: int = 0                                  # SR: part of public information
    winning_condition_description: str = ""                     # SR: part of public information

    # Property declarations
    declarations: list[dict[str, Any]] = Field(default_factory=list)    # SR: part of private information
    total_declared_values: list[float] = Field(default_factory=list)    # SR: part of game state (I do not think we actually show this to participants)

    # Market state
    market: MarketState = Field(default_factory=MarketState)  # SR: part of public information

    # SR: here we have a mix of general and game specific defintions
    # SR: all games have a gamestate, or state of the world in the definition file, but the content of this game state is game specific
    def update_state(self, event: Message) -> None:
        """Update state based on incoming event message"""
        event_handlers = {
            "players-known": self._handle_players_known,
            "phase-transition": self._handle_phase_transition,
            "assign-role": self._handle_assign_role,
            "value-signals": self._handle_value_signals,
            "assign-name": self._handle_assign_name,
            "declarations-published": self._handle_declarations_published,
            "add-order": lambda data: self._handle_market_event(event.event_type, data),
            "update-order": lambda data: self._handle_market_event(event.event_type, data),
            "delete-order": lambda data: self._handle_market_event(event.event_type, data),
            "contract-fulfilled": lambda data: self._handle_market_event(event.event_type, data),
            "asset-movement": lambda data: self._handle_market_event(event.event_type, data),
        }

        handler = event_handlers.get(event.event_type)
        if handler:
            handler(event.data)

    def _handle_players_known(self, data: dict[str, Any]) -> None:
        """Handle players-known event"""
        self.players = data["players"]

        # SR: all games have at least one phase, that phase has to end at some pointthis block has meta-information and process information that will be present in any experiment
    def _handle_phase_transition(self, data: dict[str, Any]) -> None:
        """Handle phase-transition event"""
        self.phase = data["phase"]

    def _handle_assign_role(self, data: dict[str, Any]) -> None:
        """Handle assign-role event"""
        self.wallet = data["wallet"]
        self.boundaries = data["boundaries"]
        self.tax_rate = data["taxRate"]
        self.initial_tax_rate = data["initialTaxRate"]
        self.final_tax_rate = data["finalTaxRate"]
        self.conditions = data["conditions"]
        self.property = data.get("property", {})

    def _handle_value_signals(self, data: dict[str, Any]) -> None:
        """Handle value-signals event"""
        self.value_signals = data["signals"]
        self.public_signal = data["publicSignal"]
        self.winning_condition = data["condition"]
        self.winning_condition_description = mappings.conditions[data["condition"]]
        self.tax_rate = data["taxRate"]

    def _handle_assign_name(self, data: dict[str, Any]) -> None:
        """Handle assign-name event"""
        self.player_name = data["name"]
        self.player_number = data["number"]

    def _handle_declarations_published(self, data: dict[str, Any]) -> None:
        """Handle declarations-published event"""
        self.declarations = data["declarations"]
        self.winning_condition = data["winningCondition"]
        self.winning_condition_description = mappings.conditions[data["winningCondition"]]
        self.total_declared_values = [
            sum(declaration["d"][self.winning_condition] for declaration in self.declarations)
        ]

    def _handle_market_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Handle market-related events by delegating to MarketState"""
        self.market.process_event(event_type=event_type, data=data)

        if event_type == "asset-movement":
            self.wallet[self.winning_condition]["balance"] = data["balance"]
            self.wallet[self.winning_condition]["shares"] = data["shares"]
