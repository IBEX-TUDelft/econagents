from typing import Any

from pydantic import BaseModel


class Message(BaseModel):
    message_type: str
    event_type: str
    data: dict[str, Any]
