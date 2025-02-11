import pytest
from experimental.harberger.state import MarketState, Order, Trade


@pytest.fixture
def market_state():
    """Create a fresh MarketState instance for each test"""
    return MarketState()


@pytest.fixture
def populated_market_state():
    """Create a MarketState instance populated with a sequence of events from a real trading session"""
    state = MarketState()

    # Initial ask order
    state.process_event(
        "add-order", {"order": {"id": 1, "sender": 6, "price": 100, "quantity": 4, "type": "ask", "condition": 0}}
    )

    # First trade and order update
    state.process_event("contract-fulfilled", {"from": 6, "to": 1, "price": 100, "condition": 0, "median": 100})
    state.process_event("update-order", {"order": {"id": 1, "type": "ask", "quantity": 2, "condition": 0}})

    # Second trade and order update
    state.process_event("contract-fulfilled", {"from": 6, "to": 2, "price": 100, "condition": 0, "median": 100})
    state.process_event("update-order", {"order": {"id": 1, "type": "ask", "quantity": 1, "condition": 0}})

    # Final trade and order deletion
    state.process_event("contract-fulfilled", {"from": 6, "to": 3, "price": 100, "condition": 0, "median": 100})
    state.process_event("delete-order", {"order": {"id": 1, "type": "ask", "condition": 0}})

    # New bid orders
    state.process_event(
        "add-order", {"order": {"id": 2, "sender": 3, "price": 100, "quantity": 1, "type": "bid", "condition": 0}}
    )

    state.process_event(
        "add-order", {"order": {"id": 3, "sender": 4, "price": 100, "quantity": 2, "type": "bid", "condition": 0}}
    )

    state.process_event(
        "add-order", {"order": {"id": 4, "sender": 5, "price": 100, "quantity": 2, "type": "bid", "condition": 0}}
    )

    return state


def test_add_order(market_state):
    """Test adding a new order to the market state"""
    order_data = {"order": {"id": 1, "sender": 6, "price": 100, "quantity": 4, "type": "ask", "condition": 0}}

    market_state.process_event("add-order", order_data)

    assert len(market_state.orders) == 1
    assert market_state.orders[1].id == 1
    assert market_state.orders[1].sender == 6
    assert market_state.orders[1].price == 100
    assert market_state.orders[1].quantity == 4
    assert market_state.orders[1].type == "ask"
    assert market_state.orders[1].condition == 0


def test_update_order(market_state):
    """Test updating an existing order"""
    # First add an order
    market_state.process_event(
        "add-order", {"order": {"id": 1, "sender": 6, "price": 100, "quantity": 4, "type": "ask", "condition": 0}}
    )

    # Then update it
    market_state.process_event("update-order", {"order": {"id": 1, "type": "ask", "quantity": 2, "condition": 0}})

    assert market_state.orders[1].quantity == 2
    assert market_state.orders[1].type == "ask"
    assert market_state.orders[1].condition == 0


def test_delete_order(market_state):
    """Test deleting an order"""
    # First add an order
    market_state.process_event(
        "add-order", {"order": {"id": 1, "sender": 6, "price": 100, "quantity": 4, "type": "ask", "condition": 0}}
    )

    # Then delete it
    market_state.process_event("delete-order", {"order": {"id": 1, "type": "ask", "condition": 0}})

    assert len(market_state.orders) == 0


def test_contract_fulfilled(market_state):
    """Test recording a fulfilled contract (trade)"""
    trade_data = {"from": 6, "to": 1, "price": 100, "condition": 0, "median": 100}

    market_state.process_event("contract-fulfilled", trade_data)

    assert len(market_state.trades) == 1
    assert market_state.trades[0].from_id == 6
    assert market_state.trades[0].to_id == 1
    assert market_state.trades[0].price == 100
    assert market_state.trades[0].condition == 0
    assert market_state.trades[0].median == 100


def test_best_bid_ask(populated_market_state):
    """Test finding best bid and ask prices"""
    result = populated_market_state.best_bid_ask(0)

    # We should have multiple bid orders but no ask orders
    assert result["ask"] is None  # All asks were filled
    assert result["bid"] is not None
    assert result["bid"].price == 100  # All bids were at price 100

    # Verify we have the expected number of bid orders
    bids = [o for o in populated_market_state.orders.values() if o.type == "bid"]
    assert len(bids) == 3


def test_trade_sequence(populated_market_state):
    """Test the complete sequence of trades"""
    trades = populated_market_state.trades

    assert len(trades) == 3

    # Verify the sequence of trades
    assert trades[0].from_id == 6 and trades[0].to_id == 1
    assert trades[1].from_id == 6 and trades[1].to_id == 2
    assert trades[2].from_id == 6 and trades[2].to_id == 3

    # All trades should be at price 100
    assert all(trade.price == 100 for trade in trades)

    # All trades should have the same median
    assert all(trade.median == 100 for trade in trades)
