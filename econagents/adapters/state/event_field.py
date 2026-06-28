"""State projector backed by ``GameState.update``."""

from econagents.domain.events import Message
from econagents.domain.messages import Event
from econagents.domain.state.game import GameState


class EventFieldStateProjector:
    """Apply events through the ``EventField`` mapping model."""

    def apply(self, state: GameState, event: Event) -> None:
        """Update the state in place."""
        state.update(Message.from_event(event))
