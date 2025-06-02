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


class BestPrices(BaseModel):
    best_ask: float = Field(default=float("inf"))
    best_bid: float = Field(default=float("-inf"))


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
        """
        Represents the order book, grouping orders by condition if multiple conditions exist.
        Within each condition, orders are grouped by type (ask/bid) and sorted by price.
        """
        if not self.orders:
            return "No active orders"

        # Get all unique conditions
        conditions = set(order.condition for order in self.orders.values())

        # If only one condition, use the original format
        if len(conditions) == 1:
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

        # Multiple conditions: group by condition
        result_lines = []
        for condition in sorted(conditions):
            result_lines.append(f"=== Condition {condition} ===")

            # Get orders for this condition
            condition_orders = [order for order in self.orders.values() if order.condition == condition]

            # Sort asks and bids separately
            asks = sorted(
                [order for order in condition_orders if order.type == "ask"],
                key=lambda x: x.price,
                reverse=True,
            )
            bids = sorted(
                [order for order in condition_orders if order.type == "bid"],
                key=lambda x: x.price,
                reverse=True,
            )

            # Add asks first, then bids
            for order in asks + bids:
                result_lines.append(str(order))

            # Add empty line between conditions (except for the last one)
            if condition != max(conditions):
                result_lines.append("")

        return "\n".join(result_lines)

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

    @computed_field
    def best_prices_from_orders(self) -> list[BestPrices]:
        """Get the best ask and bid prices for each condition."""
        best_prices: list[BestPrices] = [BestPrices(), BestPrices()]
        for order in self.orders.values():
            if order.type == "ask":
                if order.price < best_prices[order.condition].best_ask:
                    best_prices[order.condition] = BestPrices(best_ask=order.price)
            elif order.type == "bid":
                if order.price > best_prices[order.condition].best_bid:
                    best_prices[order.condition].best_bid = order.price
        return best_prices

    def get_orders_from_player(self, player_id: int) -> list[Order]:
        """Get all orders from a specific player."""
        return [order for order in self.orders.values() if order.sender == player_id]

    @computed_field
    def market_prices(self) -> list[Optional[float]]:
        """
        Calculates market prices based on the median of the last recorded trade for each condition.

        Returns:
            A list of prices for each condition. Returns None for conditions that have not had any trades.
        """
        prices_condition_0 = [trade.median for trade in self.trades if trade.condition == 0]
        prices_condition_1 = [trade.median for trade in self.trades if trade.condition == 1]

        return [
            prices_condition_0[-1] if prices_condition_0 else None,
            prices_condition_1[-1] if prices_condition_1 else None,
        ]

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
