from typing import Optional

from pydantic import BaseModel, Field, computed_field


class Order(BaseModel):
    id: int
    sender: int
    price: float
    quantity: float
    type: str
    condition: int
    now: bool = False


class Trade(BaseModel):
    from_id: int
    to_id: int
    price: float
    quantity: float
    condition: int
    median: Optional[float] = None


class MarketState(BaseModel):
    """
    Represents the current state of the market:
    - Active orders in an order book
    - History of recent trades
    """

    orders: dict[int, Order] = Field(default_factory=dict)
    trades: list[Trade] = Field(default_factory=list)

    @computed_field
    def order_book(self) -> str:
        asks = sorted(
            [order for order in self.orders.values() if order.type == "ask"],
            key=lambda x: x.price,
            reverse=True,
        )
        bids = sorted(
            [order for order in self.orders.values() if order.type == "bid"],
            key=lambda x: x.price,
            reverse=True,
        )
        sorted_orders = asks + bids
        return "\n".join([str(order) for order in sorted_orders])

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
            existing.quantity = order_data.get("quantity", existing.quantity)
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
