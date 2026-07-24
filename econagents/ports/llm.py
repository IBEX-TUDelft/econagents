"""LLM provider port."""

import logging
from typing import TYPE_CHECKING, Any, Optional, Protocol, Type, Union, runtime_checkable

from pydantic import BaseModel

if TYPE_CHECKING:
    from econagents.ports.tools import ToolExecutor, ToolSpec


@runtime_checkable
class LLMProvider(Protocol):
    """Interface for model providers used by roles."""

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
        """Return a raw model response or a validated structured response.

        When ``tools`` and ``tool_executor`` are provided, the adapter runs the
        provider-native tool-calling loop: it advertises the tools, executes any
        requested calls via ``tool_executor``, feeds the results back, and
        repeats up to ``max_tool_iterations`` times until the model returns a
        final answer. The return type is unchanged whether or not tools are used.

        When ``logger`` is provided, adapters log each full provider response
        (including reasoning and usage when available) to it at DEBUG level.
        """
        ...

    def build_messages(self, system_prompt: str, user_prompt: str) -> list[dict[str, Any]]:
        """Build provider-specific chat messages."""
        ...
