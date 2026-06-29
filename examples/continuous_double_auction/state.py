from typing import Literal

from pydantic import Field

from econagents.domain.messages import PhaseId
from econagents.domain.state.fields import EventField
from econagents.domain.state.game import GameState, MetaInformation, PrivateInformation, PublicInformation


class CDAMeta(MetaInformation):
    """Meta information for a continuous double auction trader."""

    game_id: int = EventField(default=0, exclude_from_mapping=True)
    phase: PhaseId = EventField(default="waiting")
    player_number: int | None = EventField(default=None)
    market_duration: int = EventField(default=10)
    summary_duration: int = EventField(default=2)


class CDAPrivate(PrivateInformation):
    """Private trader information sent only to one agent."""

    trader_type: Literal["buyer", "seller"] | None = EventField(default=None)
    limit_price: float | None = EventField(default=None)
    remaining_units: int = EventField(default=0)
    cash_balance: float = EventField(default=0.0)
    cash_flow: float = EventField(default=0.0)
    surplus: float = EventField(default=0.0)
    inventory: int = EventField(default=0)
    actions_submitted: int = EventField(default=0)


class CDAPublic(PublicInformation):
    """Public market information shared with every trader."""

    best_bid: float | None = EventField(default=None)
    best_ask: float | None = EventField(default=None)
    last_price: float | None = EventField(default=None)
    order_count: int = EventField(default=0)
    transactions: list[dict] = EventField(default_factory=list)
    market_summary: dict = EventField(default_factory=dict)


class CDAGameState(GameState):
    """Game state for the continuous double auction example."""

    meta: CDAMeta = Field(default_factory=CDAMeta)
    private_information: CDAPrivate = Field(default_factory=CDAPrivate)
    public_information: CDAPublic = Field(default_factory=CDAPublic)
