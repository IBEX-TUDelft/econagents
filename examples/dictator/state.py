from typing import Any

from pydantic import Field

from econagents.core.state.fields import EventField
from econagents.core.state.game import (
    GameState,
    MetaInformation,
    PrivateInformation,
    PublicInformation,
)


class DMeta(MetaInformation):
    """Meta information for the Dictator game."""

    game_id: int = EventField(default=0, exclude_from_mapping=True)
    phase: int = EventField(default=0, event_key="phase")
    total_phases: int = EventField(default=2)


class DPrivate(PrivateInformation):
    """Private information for the Dictator game."""

    role: str = EventField(default="")
    payout: float = EventField(default=0.0)


class DPublic(PublicInformation):
    """Public information for the Dictator game."""

    money_sent: float = EventField(default=0.0)
    money_available: float = EventField(default=10.0)
    exchange_rate: float = EventField(default=3.0)
    payouts: dict[str, float] = EventField(default_factory=dict)


class DGameState(GameState):
    """Game state for the Dictator game."""

    meta: DMeta = Field(default_factory=DMeta)
    private_information: DPrivate = Field(default_factory=DPrivate)
    public_information: DPublic = Field(default_factory=DPublic)
