import importlib.util
import json
import logging
from typing import TYPE_CHECKING, Any, Literal, Optional, Type, Union

from pydantic import BaseModel

from econagents.adapters.llm.base import BaseLLM
from econagents.ports.tools import ToolCall

if TYPE_CHECKING:
    from econagents.ports.tools import ToolExecutor, ToolSpec

_logger = logging.getLogger(__name__)

ReasoningEffort = Literal["minimal", "low", "medium", "high"]
ReasoningSummary = Literal["auto", "concise", "detailed"]


class ChatOpenAI(BaseLLM):
    """OpenAI wrapper built on the Responses API.

    Supports structured outputs via a Pydantic ``response_schema`` and exposes
    the reasoning controls available on GPT-5 and other reasoning-capable
    models. Non-reasoning models should simply leave ``reasoning_effort`` and
    ``reasoning_summary`` as ``None``.
    """

    def __init__(
        self,
        model_name: str = "gpt-5.4-mini",
        api_key: Optional[str] = None,
        reasoning_effort: Optional[ReasoningEffort] = None,
        reasoning_summary: Optional[ReasoningSummary] = None,
        response_kwargs: Optional[dict[str, Any]] = None,
    ) -> None:
        """Initialize the OpenAI LLM interface.

        Args:
            model_name: The model name to use. Defaults to ``gpt-5.4-mini``.
            api_key: The API key to use for authentication.
            reasoning_effort: Reasoning effort for reasoning-capable models.
                One of ``minimal``, ``low``, ``medium``, ``high``. ``None``
                omits the reasoning parameter entirely.
            reasoning_summary: Whether to include a reasoning summary in the
                response (reasoning-capable models only).
            response_kwargs: Extra keyword arguments forwarded to the
                Responses API call (e.g., ``temperature`` on non-reasoning
                models, ``max_output_tokens``).
        """
        self.model_name = model_name
        self.api_key = api_key
        self.reasoning_effort = reasoning_effort
        self.reasoning_summary = reasoning_summary
        self._check_openai_available()
        self._response_kwargs = response_kwargs or {}

    def _check_openai_available(self) -> None:
        """Check if OpenAI is available."""
        if not importlib.util.find_spec("openai"):
            raise ImportError("OpenAI is not installed. Install it with: pip install econagents[openai]")

    def _build_reasoning(self) -> Optional[dict[str, str]]:
        if self.reasoning_effort is None and self.reasoning_summary is None:
            return None
        reasoning: dict[str, str] = {}
        if self.reasoning_effort is not None:
            reasoning["effort"] = self.reasoning_effort
        if self.reasoning_summary is not None:
            reasoning["summary"] = self.reasoning_summary
        return reasoning

    @staticmethod
    def _to_openai_tools(tools: list["ToolSpec"]) -> list[dict[str, Any]]:
        """Convert provider-agnostic specs to Responses API tool definitions."""
        return [
            {
                "type": "function",
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            }
            for spec in tools
        ]

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
        """Get a response from the OpenAI Responses API.

        Args:
            messages: The messages for the LLM.
            tracing_extra: Extra tracing information passed to observability.
            response_schema: Optional Pydantic model used as the structured
                output format. When provided, the method returns a validated
                instance of the model; otherwise it returns the plain text
                output from the API.
            tools: Optional tool specs advertised to the model via the
                Responses API ``tools`` parameter.
            tool_executor: Async callback used to run each requested tool call.
            max_tool_iterations: Safety cap on tool-call rounds.
            logger: Optional logger; when given, every full API response
                (reasoning items, output content, usage) is logged to it at
                DEBUG level.

        Returns:
            A validated ``response_schema`` instance, or the raw text output
            if no schema was provided.

        Raises:
            ImportError: If OpenAI is not installed.
        """
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=self.api_key)

            base_kwargs: dict[str, Any] = {
                "model": self.model_name,
                **self._response_kwargs,
            }
            reasoning = self._build_reasoning()
            if reasoning is not None:
                base_kwargs["reasoning"] = reasoning

            use_tools = bool(tools) and tool_executor is not None
            tool_payload = self._to_openai_tools(tools) if use_tools else None

            conversation: list[Any] = list(messages)

            for _ in range(max_tool_iterations + 1 if use_tools else 1):
                kwargs = {**base_kwargs, "input": conversation}
                if tool_payload is not None:
                    kwargs["tools"] = tool_payload

                if response_schema is not None:
                    response = await client.responses.parse(text_format=response_schema, **kwargs)
                else:
                    response = await client.responses.create(**kwargs)

                self.observability.track_llm_call(
                    name="openai_responses",
                    model=self.model_name,
                    messages=conversation,
                    response=response,
                    metadata=tracing_extra,
                )
                self._log_response(response, logger)

                if not use_tools:
                    return response.output_parsed if response_schema is not None else response.output_text

                function_calls = [item for item in response.output if getattr(item, "type", None) == "function_call"]
                if not function_calls:
                    return response.output_parsed if response_schema is not None else response.output_text

                for item in function_calls:
                    conversation.append(
                        {
                            "type": "function_call",
                            "call_id": item.call_id,
                            "name": item.name,
                            "arguments": item.arguments,
                        }
                    )
                    result = await tool_executor(  # type: ignore[misc]
                        ToolCall(
                            id=item.call_id,
                            name=item.name,
                            arguments=json.loads(item.arguments or "{}"),
                        )
                    )
                    conversation.append(
                        {
                            "type": "function_call_output",
                            "call_id": item.call_id,
                            "output": json.dumps(result, default=str),
                        }
                    )

            _logger.warning("Max tool iterations (%s) reached; forcing a final answer.", max_tool_iterations)
            final_kwargs = {**base_kwargs, "input": conversation}
            if response_schema is not None:
                response = await client.responses.parse(text_format=response_schema, **final_kwargs)
            else:
                response = await client.responses.create(**final_kwargs)
            self._log_response(response, logger)
            return response.output_parsed if response_schema is not None else response.output_text
        except ImportError as e:
            _logger.error(f"Failed to import OpenAI: {e}")
            raise ImportError("OpenAI is not installed. Install it with: pip install econagents[openai]") from e
