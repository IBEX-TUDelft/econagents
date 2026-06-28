"""LLM response parsing ports."""

from typing import Any, Protocol, Type

from pydantic import BaseModel

from econagents.domain.messages import PhaseId
from econagents.domain.state.game import GameStateProtocol


class ResponseParserPort(Protocol):
    """Validate and convert provider responses into action dictionaries."""

    def parse(
        self,
        response: str | BaseModel,
        state: GameStateProtocol,
        phase: PhaseId,
        response_schema: Type[BaseModel] | None = None,
        logger: Any | None = None,
    ) -> dict[str, Any]:
        """Parse the provider response for a phase."""
        ...
