import importlib.util
import json
import logging
import os
from typing import TYPE_CHECKING, Any, Literal, Optional, Type, Union

from pydantic import BaseModel

from econagents.adapters.llm.base import BaseLLM
from econagents.ports.tools import ToolCall

if TYPE_CHECKING:
    from econagents.ports.tools import ToolExecutor, ToolSpec

_logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]


class ChatOpenRouter(BaseLLM):
    """OpenRouter wrapper built on its OpenAI-compatible Chat Completions API.

    OpenRouter model identifiers include the upstream provider, for example
    ``openai/gpt-5.4-mini`` or ``anthropic/claude-sonnet-4``.
    """

    def __init__(
        self,
        model_name: str = "openai/gpt-5.4-mini",
        api_key: Optional[str] = None,
        base_url: str = OPENROUTER_BASE_URL,
        site_url: Optional[str] = None,
        app_name: Optional[str] = None,
        reasoning_effort: Optional[ReasoningEffort] = None,
        reasoning_max_tokens: Optional[int] = None,
        reasoning_exclude: Optional[bool] = None,
        response_kwargs: Optional[dict[str, Any]] = None,
    ) -> None:
        """Initialize the OpenRouter LLM interface.

        Args:
            model_name: OpenRouter model identifier in ``provider/model`` form.
            api_key: OpenRouter API key. When omitted, ``OPENROUTER_API_KEY``
                is read when a request is made.
            base_url: OpenRouter-compatible API base URL.
            site_url: Optional app URL sent as the ``HTTP-Referer`` header.
            app_name: Optional app name sent as ``X-OpenRouter-Title``.
            reasoning_effort: Normalized OpenRouter reasoning effort.
            reasoning_max_tokens: Explicit reasoning token budget. This cannot
                be combined with ``reasoning_effort``.
            reasoning_exclude: Whether reasoning tokens should be omitted from
                the response while still being used by the model.
            response_kwargs: Extra keyword arguments forwarded to Chat
                Completions. OpenRouter-only fields such as provider routing
                preferences can be supplied under ``extra_body``.
        """
        if reasoning_effort is not None and reasoning_max_tokens is not None:
            raise ValueError("reasoning_effort and reasoning_max_tokens cannot be used together")

        self._check_openai_available()
        self.model_name = model_name
        self.api_key = api_key
        self.base_url = base_url
        self.site_url = site_url
        self.app_name = app_name
        self.reasoning_effort = reasoning_effort
        self.reasoning_max_tokens = reasoning_max_tokens
        self.reasoning_exclude = reasoning_exclude
        self._response_kwargs = response_kwargs or {}

    @staticmethod
    def _check_openai_available() -> None:
        """Check that the OpenAI compatibility client is available."""
        if not importlib.util.find_spec("openai"):
            raise ImportError("OpenRouter requires the OpenAI client. Install it with: pip install econagents")

    def _get_api_key(self) -> str:
        api_key = self.api_key or os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError("Set OPENROUTER_API_KEY or pass api_key to ChatOpenRouter")
        return api_key

    def _default_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.site_url:
            headers["HTTP-Referer"] = self.site_url
        if self.app_name:
            headers["X-OpenRouter-Title"] = self.app_name
        return headers

    def _build_reasoning(self) -> Optional[dict[str, Any]]:
        reasoning: dict[str, Any] = {}
        if self.reasoning_effort is not None:
            reasoning["effort"] = self.reasoning_effort
        if self.reasoning_max_tokens is not None:
            reasoning["max_tokens"] = self.reasoning_max_tokens
        if self.reasoning_exclude is not None:
            reasoning["exclude"] = self.reasoning_exclude
        return reasoning or None

    @staticmethod
    def _to_openrouter_tools(tools: list["ToolSpec"]) -> list[dict[str, Any]]:
        """Convert provider-agnostic specs to Chat Completions tools."""
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                },
            }
            for spec in tools
        ]

    @staticmethod
    def _response_format(response_schema: Type[BaseModel]) -> dict[str, Any]:
        from openai.lib._pydantic import to_strict_json_schema

        return {
            "type": "json_schema",
            "json_schema": {
                "name": response_schema.__name__,
                "strict": True,
                "schema": to_strict_json_schema(response_schema),
            },
        }

    @staticmethod
    def _message_dict(message: Any) -> dict[str, Any]:
        """Serialize an assistant message without dropping reasoning blocks."""
        if hasattr(message, "model_dump"):
            dumped = message.model_dump(exclude_none=True)
            return {
                field: dumped[field]
                for field in ("role", "content", "tool_calls", "reasoning", "reasoning_details")
                if field in dumped
            }

        result: dict[str, Any] = {
            "role": "assistant",
            "content": getattr(message, "content", None),
        }
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            result["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in tool_calls
            ]
        for field in ("reasoning", "reasoning_details"):
            value = getattr(message, field, None)
            if value is not None:
                result[field] = value
        return result

    @staticmethod
    def _result(message: Any, response_schema: Optional[Type[BaseModel]]) -> Union[str, BaseModel]:
        content = message.content or ""
        if response_schema is not None:
            return response_schema.model_validate_json(content)
        return content

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
        """Get a response from OpenRouter and run any requested tools."""
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(
                api_key=self._get_api_key(),
                base_url=self.base_url,
                default_headers=self._default_headers(),
            )

            base_kwargs: dict[str, Any] = {
                "model": self.model_name,
                **self._response_kwargs,
            }
            reasoning = self._build_reasoning()
            if reasoning is not None:
                extra_body = dict(base_kwargs.get("extra_body") or {})
                extra_body["reasoning"] = reasoning
                base_kwargs["extra_body"] = extra_body
            if response_schema is not None:
                base_kwargs["response_format"] = self._response_format(response_schema)

            use_tools = bool(tools) and tool_executor is not None
            tool_payload = self._to_openrouter_tools(tools) if use_tools else None
            conversation: list[Any] = list(messages)

            for _ in range(max_tool_iterations + 1 if use_tools else 1):
                kwargs = {**base_kwargs, "messages": conversation}
                if tool_payload is not None:
                    kwargs["tools"] = tool_payload

                response = await client.chat.completions.create(**kwargs)
                self.observability.track_llm_call(
                    name="openrouter_chat_completion",
                    model=self.model_name,
                    messages=conversation,
                    response=response,
                    metadata=tracing_extra,
                )
                self._log_response(response, logger)

                message = response.choices[0].message
                tool_calls = message.tool_calls or []
                if not use_tools or not tool_calls:
                    return self._result(message, response_schema)

                conversation.append(self._message_dict(message))
                for call in tool_calls:
                    result = await tool_executor(  # type: ignore[misc]
                        ToolCall(
                            id=call.id,
                            name=call.function.name,
                            arguments=json.loads(call.function.arguments or "{}"),
                        )
                    )
                    conversation.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "name": call.function.name,
                            "content": json.dumps(result, default=str),
                        }
                    )

            _logger.warning("Max tool iterations (%s) reached; forcing a final answer.", max_tool_iterations)
            final = await client.chat.completions.create(**base_kwargs, messages=conversation)
            self.observability.track_llm_call(
                name="openrouter_chat_completion",
                model=self.model_name,
                messages=conversation,
                response=final,
                metadata=tracing_extra,
            )
            self._log_response(final, logger)
            return self._result(final.choices[0].message, response_schema)
        except ImportError as e:
            _logger.error("Failed to import the OpenAI compatibility client: %s", e)
            raise ImportError("OpenRouter requires the OpenAI client. Install it with: pip install econagents") from e
