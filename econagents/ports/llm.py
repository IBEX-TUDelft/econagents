"""LLM provider port."""

from typing import Any, Optional, Protocol, Type, Union, runtime_checkable

from pydantic import BaseModel


@runtime_checkable
class LLMProvider(Protocol):
    """Interface for model providers used by roles."""

    async def get_response(
        self,
        messages: list[dict[str, Any]],
        tracing_extra: dict[str, Any],
        response_schema: Optional[Type[BaseModel]] = None,
    ) -> Union[str, BaseModel]:
        """Return a raw model response or a validated structured response."""
        ...

    def build_messages(self, system_prompt: str, user_prompt: str) -> list[dict[str, Any]]:
        """Build provider-specific chat messages."""
        ...
