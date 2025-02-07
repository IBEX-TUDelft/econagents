from typing import Any, Optional
from pydantic import BaseModel, Field


class Mappings(BaseModel):
    roles: dict[int, str]
    phases: dict[int, str]
    conditions: dict[int, str]


class State(BaseModel):
    # Basic info
    player_name: str = ""
    player_number: Optional[int] = None
    players: list[dict[str, Any]] = Field(default_factory=list)
    phase: int = 0

    # Wallet and market info
    wallet: dict[str, Any] = Field(default_factory=dict)
    tax_rate: float = 0
    initial_tax_rate: float = 0
    final_tax_rate: float = 0

    # Value boundaries and conditions
    boundaries: dict[str, Any] = Field(default_factory=dict)
    conditions: list[dict[str, Any]] = Field(default_factory=list)
    property: dict[str, Any] = Field(default_factory=dict)

    # Market signals
    value_signals: list[float] = Field(default_factory=list)
    public_signal: list[float] = Field(default_factory=list)
    winning_condition: int = 0
    winning_condition_description: str = ""

    # Property declarations
    declarations: list[dict[str, Any]] = Field(default_factory=list)
    total_declared_values: list[float] = Field(default_factory=list)


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
