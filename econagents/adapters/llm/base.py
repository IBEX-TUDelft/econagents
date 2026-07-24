import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Optional, Type, Union

from pydantic import BaseModel

from econagents.adapters.llm.observability import ObservabilityProvider, get_observability_provider
from econagents.ports.llm import LLMProvider

if TYPE_CHECKING:
    from econagents.ports.tools import ToolExecutor, ToolSpec


class BaseLLM(ABC):
    """Base class for LLM implementations."""

    observability: ObservabilityProvider = get_observability_provider("noop")

    @staticmethod
    def _log_response(response: Any, logger: Optional[logging.Logger]) -> None:
        """Log a full provider response at DEBUG level.

        Serializes via the SDK model's ``model_dump_json`` when available so
        the whole response is captured — reasoning items (including any
        summary), output content, and usage — falling back to ``str``. Logging
        must never break the call, so serialization errors are swallowed.
        """
        if logger is None:
            return
        try:
            serialized = response.model_dump_json(indent=2)
        except Exception:  # noqa: BLE001
            serialized = str(response)
        logger.debug("\n+-----LLM RESPONSE----+\n" + f"{serialized}\n+------------------+")

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
        tools: Optional[list["ToolSpec"]] = None,
        tool_executor: Optional["ToolExecutor"] = None,
        max_tool_iterations: int = 5,
        logger: Optional[logging.Logger] = None,
    ) -> Union[str, BaseModel]:
        """Get a response from the LLM.

        Args:
            messages: The messages for the LLM.
            tracing_extra: Extra tracing information passed to observability.
            response_schema: Optional Pydantic model to use as the structured
                output schema. Providers that support structured outputs should
                return a validated instance of this model.
            tools: Optional provider-agnostic tool specs to advertise. When
                given together with ``tool_executor``, the adapter runs the
                native tool-calling loop before returning the final answer.
            tool_executor: Async callback that executes a single requested tool
                call and returns its (JSON-serializable) result.
            max_tool_iterations: Safety cap on tool-call rounds per response.
            logger: Optional logger the adapter uses to log each full provider
                response (including reasoning and usage when available) at
                DEBUG level. When ``None``, responses are not logged.

        Returns:
            Either a validated ``response_schema`` instance or a raw string,
            depending on provider capabilities and whether a schema was given.
        """
        ...
