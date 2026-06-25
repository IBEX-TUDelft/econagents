import importlib.util
import json
import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Type

from pydantic import BaseModel

from econagents.adapters.llm.base import BaseLLM
from econagents.ports.tools import ToolCall

if TYPE_CHECKING:
    from econagents.ports.tools import ToolExecutor, ToolSpec

logger = logging.getLogger(__name__)


class ChatOllama(BaseLLM):
    """A wrapper for LLM queries using Ollama."""

    def __init__(
        self,
        model_name: str,
        host: Optional[str] = None,
        response_kwargs: Optional[dict[str, Any]] = None,
    ) -> None:
        """Initialize the Ollama LLM interface.

        Args:
            model_name: The model name to use.
            host: The host for the Ollama API (e.g., "http://localhost:11434").
            response_kwargs: Extra keyword arguments forwarded to ``chat``.
        """
        self._check_ollama_available()
        self.model_name = model_name
        self.host = host
        self._response_kwargs = response_kwargs or {}

    def _check_ollama_available(self) -> None:
        """Check if Ollama is available."""
        if not importlib.util.find_spec("ollama"):
            raise ImportError("Ollama is not installed. Install it with: pip install econagents[ollama]")

    @staticmethod
    def _to_ollama_tools(tools: list["ToolSpec"]) -> list[dict[str, Any]]:
        """Convert provider-agnostic specs to Ollama tool definitions."""
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

    async def get_response(
        self,
        messages: List[Dict[str, Any]],
        tracing_extra: Dict[str, Any],
        response_schema: Optional[Type[BaseModel]] = None,
        tools: Optional[list["ToolSpec"]] = None,
        tool_executor: Optional["ToolExecutor"] = None,
        max_tool_iterations: int = 5,
    ) -> str:
        """Get a response from Ollama.

        Args:
            messages: The messages for the LLM.
            tracing_extra: The extra tracing information.
            response_schema: Optional Pydantic model. When provided, its JSON
                schema is passed to Ollama via ``format`` so the local model
                is guided to emit matching JSON. The raw string is still
                returned; the agent layer handles validation.
            tools: Optional tool specs advertised to the model.
            tool_executor: Async callback used to run each requested tool call.
            max_tool_iterations: Safety cap on tool-call rounds.

        Returns:
            The response text from Ollama.

        Raises:
            ImportError: If Ollama is not installed.
        """
        try:
            from ollama import AsyncClient

            client = AsyncClient(host=self.host)

            kwargs: Dict[str, Any] = dict(self._response_kwargs)
            if response_schema is not None:
                kwargs["format"] = response_schema.model_json_schema()

            use_tools = bool(tools) and tool_executor is not None
            if use_tools:
                kwargs["tools"] = self._to_ollama_tools(tools)

            conversation: list[Any] = list(messages)

            for _ in range(max_tool_iterations + 1 if use_tools else 1):
                response = await client.chat(
                    model=self.model_name,
                    messages=conversation,
                    **kwargs,
                )

                self.observability.track_llm_call(
                    name="ollama_chat_completion",
                    model=self.model_name,
                    messages=conversation,
                    response=response,
                    metadata=tracing_extra,
                )

                message = response["message"]
                if not use_tools:
                    return message["content"]

                tool_calls = message.get("tool_calls") or []
                if not tool_calls:
                    return message["content"]

                conversation.append(message)
                for call in tool_calls:
                    fn = call["function"]
                    arguments = fn.get("arguments") or {}
                    if isinstance(arguments, str):
                        arguments = json.loads(arguments or "{}")
                    result = await tool_executor(  # type: ignore[misc]
                        ToolCall(id=fn["name"], name=fn["name"], arguments=arguments)
                    )
                    conversation.append(
                        {
                            "role": "tool",
                            "tool_name": fn["name"],
                            "content": json.dumps(result, default=str),
                        }
                    )

            logger.warning("Max tool iterations (%s) reached; returning last response.", max_tool_iterations)
            final = await client.chat(model=self.model_name, messages=conversation, **kwargs)
            return final["message"]["content"]

        except ImportError as e:
            logger.error(f"Failed to import Ollama: {e}")
            raise ImportError("Ollama is not installed. Install it with: pip install econagents[ollama]") from e
