from typing import Any

from pydantic import Field

from econagents.core.state.fields import EventField
from econagents.core.state.game import GameState, MetaInformation, PrivateInformation, PublicInformation


class PDMeta(MetaInformation):
    """Meta information for the Prisoner's Dilemma game."""

    game_id: int = EventField(default=0, exclude_from_mapping=True)
    phase: int = EventField(default=0, event_key="round")
    total_rounds: int = EventField(default=5)


class PDPrivate(PrivateInformation):
    """Private information for the Prisoner's Dilemma game."""

    total_score: int = EventField(default=0)


class PDPublic(PublicInformation):
    """Public information for the Prisoner's Dilemma game."""

    history: list[dict[str, Any]] = EventField(default_factory=list)


class PDGameState(GameState):
    """Game state for the Prisoner's Dilemma game."""

    meta: PDMeta = Field(default_factory=PDMeta)
    private_information: PDPrivate = Field(default_factory=PDPrivate)
    public_information: PDPublic = Field(default_factory=PDPublic)
