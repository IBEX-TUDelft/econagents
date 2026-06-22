from typing import Any

from pydantic import BaseModel

from econagents.domain.messages import Event


class Message(BaseModel):
    """A message from the server to the agent."""

    message_type: str
    """Type of message"""
    event_type: str
    """Type of event"""
    data: dict[str, Any]
    """Data associated with the message"""

    @classmethod
    def from_event(cls, event: Event) -> "Message":
        """Create a transport message from a domain event."""
        return cls(message_type="event", event_type=event.type, data=event.data)

    def to_event(self) -> Event:
        """Convert this transport message to a domain event."""
        return Event(type=self.event_type, data=self.data, source=self.message_type)
