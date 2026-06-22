from abc import ABC, abstractmethod
from typing import Any, Optional, Type, Union

from pydantic import BaseModel

from econagents.adapters.llm.observability import ObservabilityProvider, get_observability_provider
from econagents.ports.llm import LLMProvider


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
        response_schema: Optional[Type[BaseModel]] = None,
    ) -> Union[str, BaseModel]:
        """Get a response from the LLM.

        Args:
            messages: The messages for the LLM.
            tracing_extra: Extra tracing information passed to observability.
            response_schema: Optional Pydantic model to use as the structured
                output schema. Providers that support structured outputs should
                return a validated instance of this model.

        Returns:
            Either a validated ``response_schema`` instance or a raw string,
            depending on provider capabilities and whether a schema was given.
        """
        ...
