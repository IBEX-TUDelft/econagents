"""LLM provider port."""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional, Protocol, Type, Union, runtime_checkable

from pydantic import BaseModel

if TYPE_CHECKING:
    from econagents.ports.tools import ToolExecutor, ToolSpec


@dataclass(frozen=True)
class LLMCallRecord:
    """What a provider reported about one model response, including one whose output failed to parse.

    Adapters that support it report a record for every provider response they receive (see
    ``econagents.adapters.llm.capture_llm_calls``). ``finish_reason`` is ``"completed"`` for a complete
    response, the provider's incomplete reason (for example ``"max_output_tokens"`` or
    ``"content_filter"``) otherwise, and ``None`` when the provider gave none. ``usage`` holds
    ``input_tokens``, ``output_tokens`` and ``reasoning_tokens`` when supplied. ``raw_output`` is the
    model's text output (``None`` when it produced none). ``parse_error`` is set when a structured
    output could not be parsed into the requested schema; the adapter then re-raises that error.
    ``response_error`` is set instead when the provider's HTTP response was not a model response at
    all (for example a non-JSON page from a proxy); no model output was received and the adapter
    re-raises the decoding error.
    """

    provider: str
    model: Optional[str]
    finish_reason: Optional[str]
    usage: Optional[dict[str, Optional[int]]]
    raw_output: Optional[str]
    parse_error: Optional[str] = None
    response_error: Optional[str] = None


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
