from typing import Any

from pydantic import BaseModel


class Message(BaseModel):
    msg_type: str
    event_type: str
    data: dict[str, Any]
