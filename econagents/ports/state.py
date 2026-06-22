"""State projection ports."""

from typing import Protocol

from econagents.domain.messages import Event
from econagents.domain.state.game import GameState


class StateProjectorPort(Protocol):
    """Apply domain events to an agent-local game state."""

    def apply(self, state: GameState, event: Event) -> None:
        """Update state in response to an event."""
        ...
