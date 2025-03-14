Managing State
==============

Overview
--------

The state management system in the econagents framework provides a structured approach to handling game state, events, and data flow in experiments. This document explains the state management architecture.

Core Components
---------------

GameState Architecture
~~~~~~~~~~~~~~~~~~~~~~

The framework uses a hierarchical state structure with three main components:

* **MetaInformation**: Game-level metadata such as player information, game ID, and phase
* **PrivateInformation**: Player-specific data not visible to other players
* **PublicInformation**: Shared data visible to all players

Event-Driven Updates
~~~~~~~~~~~~~~~~~~~~

State updates are driven by events, which are processed through:

* **Property Mappings**: Automatic mapping of event data to state properties 
* **Custom Event Handlers**: Game-specific logic for handling complex events

EventField System
~~~~~~~~~~~~~~~~~

``EventField`` extends Pydantic fields with event-related metadata:

* **event_key**: Specifies the key in event data that maps to this field. If not provided, the field name will be used.
* **events/exclude_events**: Controls which events can update this field
* **exclude_from_mapping**: Prevents automatic mapping for this field

Example Implementation
----------------------

The following TUDelft-IBEX/harberger example demonstrates how to extend the base state system for a specific experiment.

HarbergerMetaInformation
~~~~~~~~~~~~~~~~~~~~~~~~

This class extends the base ``MetaInformation`` class and captures meta information about the game, such as the player name, number, and the list of players.

.. code-block:: python

    class HarbergerMetaInformation(MetaInformation):
        player_name: Optional[str] = EventField(default=None, event_key="name")
        player_number: Optional[int] = EventField(default=None, event_key="number")
        players: list[dict[str, Any]] = EventField(default_factory=list, event_key="players")
        phase: int = EventField(default=0, event_key="phase")


HarbergerPrivateInformation
~~~~~~~~~~~~~~~~~~~~~~~~~~~

This class extends the base ``PrivateInformation`` class and captures information that is private to the player, such as the player's wallet and private value signals.

.. code-block:: python

    class HarbergerPrivateInformation(PrivateInformation):
        wallet: list[dict[str, Any]] = EventField(default_factory=list)
        value_signals: list[float] = EventField(default_factory=list, event_key="signals")
        declarations: list[dict[str, Any]] = EventField(default_factory=list)
        property: dict[str, Any] = EventField(default_factory=dict, exclude_events=["profit"])

This class manages player-specific information:

* Wallet balances and assets
* Private value signals received by the player
* Property declarations
* Property ownership details. This field is not updated on "profit" events.

HarbergerPublicInformation
~~~~~~~~~~~~~~~~~~~~~~~~~~

This class extends the base ``PublicInformation`` class and captures information that is shared across all players, such as the tax rates, market state, and winning condition.

.. code-block:: python

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

        def winning_condition_description(self) -> dict[str, Any]:
            return self.conditions[self.winning_condition]

This class manages shared information visible to all players:

* Tax rates (current, initial, and final)
* Value boundaries (max, min) for each possible development Condition
* Market state and Public value signals about values
* Winning Condition, the development Condition actually selected

HarbergerGameState
~~~~~~~~~~~~~~~~~~

Finally, you can put everything together in the game state class.

.. code-block:: python

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

The main game state class:

* Composes the specialized information classes
* Provides custom handlers for market events; given that in this example, the order book needs to be updated on the agent's side

Event Processing Flow
---------------------

1. Events are received as ``Message`` objects with ``event_type`` and ``data``
2. The ``GameState.update`` method processes these events:

   * First checks for custom handlers via ``get_custom_handlers()``
   * Falls back to property mappings via keys and names if no custom handler exists

If required, you can customize the event processing flow by overriding the ``update`` method.

Integration with Market State
-----------------------------

econagents also provides an experimental implementation of a market state class that can be used to keep track of the order book and recent trades, on each player's side.

.. code-block:: python

    class MarketState(BaseModel):
        """
        Represents the current state of the market:
        - Active orders in an order book
        - History of recent trades
        """

        orders: dict[int, Order] = Field(default_factory=dict)
        trades: list[Trade] = Field(default_factory=list)

Market events are processed through the ``process_event`` method, which delegates to specialized handlers:

* ``_on_add_order``: Adds new orders to the order book
* ``_on_update_order``: Updates existing orders (e.g., after partial fills)
* ``_on_delete_order``: Removes orders from the book (filled or canceled)
* ``_on_contract_fulfilled``: Records completed trades
