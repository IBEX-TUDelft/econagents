from pydantic import Field
from traitlets import Any

from econagents.core.state.fields import EventField
from econagents.core.state.game import (
    GameState,
    MetaInformation,
    PrivateInformation,
    PublicInformation,
)


class PGMeta(MetaInformation):
    """Meta information for the Public Goods game."""

    game_id: int = EventField(default=0, exclude_from_mapping=True)
    phase: int = EventField(default=0, event_key="phase")
    total_phases: int = EventField(default=2)
    num_players: int = EventField(default=4)
    personality: str = EventField(default="cooperative", exclude_from_mapping=True)


class PGPrivate(PrivateInformation):
    """Private information for the Public Goods game."""

    player_id: str = EventField(default="", event_key="player_id")
    initial_endowment: float = EventField(default=20.0, event_key="initial_endowment")
    contribution: float = EventField(default=0.0)
    your_payoff: float = EventField(default=0.0, event_key="your_payoff")


class PGPublic(PublicInformation):
    """Public information for the Public Goods game."""

    initial_endowment: float = EventField(default=20.0, event_key="initial_endowment")
    public_good_efficiency: float = EventField(
        default=0.5, event_key="public_good_efficiency"
    )
    total_contribution: float = EventField(default=0.0, event_key="total_contribution")
    contributions: dict[str, float] = EventField(
        default_factory=dict, event_key="contributions"
    )
    payoffs: dict[str, float] = EventField(default_factory=dict, event_key="payoffs")
    num_players: int = EventField(default=4, event_key="num_players")


class PGGameState(GameState):
    """Game state for the Public Goods game."""

    meta: PGMeta = Field(default_factory=PGMeta)
    private_information: PGPrivate = Field(default_factory=PGPrivate)
    public_information: PGPublic = Field(default_factory=PGPublic)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.meta.personality = kwargs["personality"]
