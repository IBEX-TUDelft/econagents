import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Optional, Type, Union

from pydantic import BaseModel

from econagents.adapters.llm.observability import ObservabilityProvider, get_observability_provider
from econagents.adapters.llm.trimming import check_token_limit, encoding_for, trim_to_tokens
from econagents.ports.llm import LLMProvider

if TYPE_CHECKING:
    from econagents.ports.tools import ToolExecutor, ToolSpec

_logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 120.0
"""Seconds one request to the provider may take. The ``openai`` package waits 600 seconds by default."""


def sdk_client_options(timeout: Optional[float], max_retries: Optional[int]) -> dict[str, Any]:
    """The ``openai`` client options for a request timeout and a retry count; ``None`` leaves the package's default.

    Raises:
        ValueError: If ``timeout`` is not a positive number or ``max_retries`` is not a non-negative integer.
    """
    options: dict[str, Any] = {}
    if timeout is not None:
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError(f"timeout must be a positive number of seconds or None, got {timeout!r}")
        options["timeout"] = float(timeout)
    if max_retries is not None:
        if isinstance(max_retries, bool) or not isinstance(max_retries, int) or max_retries < 0:
            raise ValueError(f"max_retries must be a non-negative integer or None, got {max_retries!r}")
        options["max_retries"] = max_retries
    return options


class BaseLLM(ABC):
    """Base class for LLM implementations."""

    observability: ObservabilityProvider = get_observability_provider("noop")
    max_message_tokens: Optional[int] = None

    def _set_max_message_tokens(self, max_message_tokens: Optional[int]) -> None:
        """Set the token limit that ``build_messages`` applies to each message.

        ``None`` leaves messages whole. Any other value is validated and the tokenizer for
        ``model_name`` is loaded, so a wrong value or a missing tiktoken fails here and not
        during a game. Call it once ``model_name`` is set.

        Raises:
            ValueError: If the limit is not a positive integer.
            ImportError: If tiktoken is not installed.
        """
        if max_message_tokens is not None:
            check_token_limit(max_message_tokens, "max_message_tokens")
            encoding_for(getattr(self, "model_name", None))
        self.max_message_tokens = max_message_tokens

    def _trim_content(self, role: str, content: str) -> str:
        """Cut one message's text to ``max_message_tokens`` tokens and log a WARNING when it was cut."""
        if self.max_message_tokens is None:
            return content
        trimmed = trim_to_tokens(content, self.max_message_tokens, model=getattr(self, "model_name", None))
        if trimmed.tokens_after < trimmed.tokens_before:
            _logger.warning(
                "%s message trimmed from %s to %s tokens", role, trimmed.tokens_before, trimmed.tokens_after
            )
        return trimmed.text

    @staticmethod
    def _log_response(response: Any, logger: Optional[logging.Logger]) -> None:
        """Log a full provider response at DEBUG level.

        Serializes via the SDK model's ``model_dump_json`` when available so
        the whole response is captured — reasoning items (including any
        summary), output content, and usage — falling back to ``str``. Nothing
        is serialized unless the logger has DEBUG enabled. Pydantic's serializer
        warnings are off: the SDK builds parsed responses with an unbound
        generic, so every structured-output response would warn although the
        JSON is complete. Logging must never break the call, so serialization
        errors are swallowed.
        """
        if logger is None or not logger.isEnabledFor(logging.DEBUG):
            return
        try:
            serialized = response.model_dump_json(indent=2, warnings=False)
        except Exception:  # noqa: BLE001
            serialized = str(response)
        logger.debug("\n+-----LLM RESPONSE----+\n" + f"{serialized}\n+------------------+")

    def build_messages(self, system_prompt: str, user_prompt: str) -> list[dict[str, Any]]:
        """Build messages for the LLM.

        When ``max_message_tokens`` is set, each prompt is cut to its first
        ``max_message_tokens`` tokens. A prompt at or under the limit is not changed.

        Args:
            system_prompt: The system prompt for the LLM.
            user_prompt: The user prompt for the LLM.

        Returns:
            The messages for the LLM.
        """
        return [
            {"role": "system", "content": self._trim_content("system", system_prompt)},
            {"role": "user", "content": self._trim_content("user", user_prompt)},
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
