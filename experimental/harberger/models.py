from typing import Any, Optional
from pydantic import BaseModel


class Mappings(BaseModel):
    roles: dict[int, str]
    phases: dict[int, str]
    conditions: dict[int, str]


class Message(BaseModel):
    msg_type: str
    event_type: str
    data: dict[str, Any]


mappings = Mappings(
    roles={
        1: "Speculator",
        2: "Developer",
        3: "Owner",
    },
    phases={
        0: "Introduction",
        1: "Presentation",
        2: "Declaration",
        3: "Speculation",
        4: "Reconciliation",
        5: "Transition",
        6: "Market",
        7: "Declaration",
        8: "Speculation",
        9: "Results",
    },
    conditions={0: "noProject", 1: "projectA"},
)
