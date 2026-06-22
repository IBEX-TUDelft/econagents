"""Stable domain messages independent of any server protocol."""

from typing import Any, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

PhaseId: TypeAlias = int | str
PlayerId: TypeAlias = int | str


class Event(BaseModel):
    """An event observed by an agent after protocol decoding."""

    type: str
    data: dict[str, Any] = Field(default_factory=dict)
    source: str | None = None
    raw: Any | None = None

    model_config = ConfigDict(arbitrary_types_allowed=True)


class Action(BaseModel):
    """An agent action before protocol encoding."""

    type: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] | None = None

    def as_payload(self) -> dict[str, Any]:
        """Return the dict payload that should be encoded for transport."""
        if self.raw is not None:
            return self.raw
        if self.type is None:
            return self.payload
        return {"type": self.type, **self.payload}


class AgentContext(BaseModel):
    """Stable identity for one simulated player in an experiment."""

    game_id: int
    agent_id: PlayerId
    role_id: int | None = None
