from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable

from econagents.llm.observability import ObservabilityProvider, get_observability_provider


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for LLM providers."""

    async def get_response(
        self,
        messages: list[dict[str, Any]],
        tracing_extra: dict[str, Any],
        **kwargs: Any,
    ) -> str:
        """Get a response from the LLM."""
        ...

    def build_messages(self, system_prompt: str, user_prompt: str) -> list[dict[str, Any]]:
        """Build messages for the LLM."""
        ...


class BaseLLM(ABC):
    """Base class for LLM implementations."""

    observability: ObservabilityProvider = get_observability_provider("noop")

    def build_messages(self, system_prompt: str, user_prompt: str) -> list[dict[str, Any]]:
        """Build messages for the LLM.

        Args:
            system_prompt: The system prompt for the LLM.
            user_prompt: The user prompt for the LLM.

        Returns:
            The messages for the LLM.
        """
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    @abstractmethod
    async def get_response(
        self,
        messages: list[dict[str, Any]],
        tracing_extra: dict[str, Any],
        **kwargs: Any,
    ) -> str:
        """Get a response from the LLM.

        Args:
            messages: The messages for the LLM.
            tracing_extra: The extra tracing information.
            **kwargs: Additional arguments to pass to the LLM.

        Returns:
            The response from the LLM.
        """
        ...
