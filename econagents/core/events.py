from typing import Any

from pydantic import BaseModel


class Message(BaseModel):
    """A message from the server to the agent."""

    message_type: str
    """Type of message"""
    event_type: str
    """Type of event"""
    data: dict[str, Any]
    """Data associated with the message"""
