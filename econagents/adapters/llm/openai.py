import importlib.util
import inspect
import json
import logging
from typing import TYPE_CHECKING, Any, Literal, Optional, Type, Union

from pydantic import BaseModel

from econagents.adapters.llm.base import DEFAULT_TIMEOUT_S, BaseLLM, sdk_client_options
from econagents.adapters.llm.call_records import report_llm_call
from econagents.ports.llm import LLMCallRecord
from econagents.ports.tools import ToolCall

if TYPE_CHECKING:
    from econagents.ports.tools import ToolExecutor, ToolSpec

_logger = logging.getLogger(__name__)

ReasoningEffort = Literal["none", "low", "medium", "high", "xhigh"]
ReasoningSummary = Literal["auto", "concise", "detailed"]
MODERATION_MODEL = "omni-moderation-latest"


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
        max_message_tokens: Optional[int] = None,
        timeout: Optional[float] = DEFAULT_TIMEOUT_S,
        max_retries: Optional[int] = None,
        moderation: Union[bool, str] = False,
        safety_identifier: Optional[str] = None,
    ) -> None:
        """Initialize the OpenAI LLM interface.

        Args:
            model_name: The model name to use. Defaults to ``gpt-5.4-mini``.
            api_key: The API key to use for authentication.
            reasoning_effort: Reasoning effort for reasoning-capable models.
                ``gpt-5.4-mini`` supports ``none``, ``low``, ``medium``,
                ``high``, and ``xhigh``. Supported values can vary for other
                models. Python ``None`` omits the reasoning parameter entirely.
            reasoning_summary: Whether to include a reasoning summary in the
                response (reasoning-capable models only).
            response_kwargs: Extra keyword arguments forwarded to the
                Responses API call (e.g., ``temperature`` on non-reasoning
                models, ``max_output_tokens``).
            max_message_tokens: Cut the system prompt and the user prompt to
                at most this many tokens each. ``None`` sends them whole.
                Tokens are counted with tiktoken's encoding for
                ``model_name`` (``o200k_base`` when tiktoken does not know the
                model). Requires ``pip install econagents[tokens]``.
            timeout: Seconds one request may take before it fails with a
                timeout, which counts as a failed attempt. Defaults to 120.
                ``None`` leaves the ``openai`` package's default (600).
            max_retries: How often the ``openai`` package sends a failed
                request again (connection errors, timeouts and 408, 409, 429
                and 5xx answers). ``None`` leaves the package's default (2);
                ``0`` makes one model call one request.
            moderation: Ask OpenAI to moderate the request's input and the
                model's output on the same call. ``True`` uses
                ``omni-moderation-latest``; a string names another moderation
                model. The result never blocks or changes the response: it is
                reported in ``LLMCallRecord.moderation`` and a WARNING is
                logged for flagged content.
            safety_identifier: A stable identifier for the end user behind the
                requests, sent as ``safety_identifier``, so OpenAI can act on
                one user instead of the whole organization. Send a hash, not a
                name or an address.

        Raises:
            ValueError: If ``timeout``, ``max_retries``, ``moderation`` or
                ``safety_identifier`` has an invalid value.
            ImportError: If the installed ``openai`` package is too old for
                ``moderation`` or ``safety_identifier``.
        """
        self.model_name = model_name
        self.api_key = api_key
        self.reasoning_effort = reasoning_effort
        self.reasoning_summary = reasoning_summary
        self._check_openai_available()
        self._response_kwargs = response_kwargs or {}
        self._set_max_message_tokens(max_message_tokens)
        self._client_options = sdk_client_options(timeout, max_retries)
        self._guardrail_kwargs = self._build_guardrail_kwargs(moderation, safety_identifier)

    def _build_guardrail_kwargs(self, moderation: Union[bool, str], safety_identifier: Optional[str]) -> dict[str, Any]:
        """The Responses API parameters for ``moderation`` and ``safety_identifier``."""
        kwargs: dict[str, Any] = {}
        if moderation is not False:
            if moderation is not True and (not isinstance(moderation, str) or not moderation):
                raise ValueError(f"moderation must be True, False or a moderation model name, got {moderation!r}")
            kwargs["moderation"] = {"model": MODERATION_MODEL if moderation is True else moderation}
        if safety_identifier is not None:
            if not isinstance(safety_identifier, str) or not safety_identifier:
                raise ValueError(f"safety_identifier must be a non-empty string or None, got {safety_identifier!r}")
            kwargs["safety_identifier"] = safety_identifier
        unsupported = sorted(set(kwargs) - _responses_parameters()) if kwargs else []
        if unsupported:
            raise ImportError(
                f"{' and '.join(unsupported)} need a newer openai package than the one installed. "
                "Upgrade it with: pip install -U openai"
            )
        return kwargs

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

    async def _request(
        self,
        client: Any,
        response_schema: Optional[Type[BaseModel]],
        kwargs: dict[str, Any],
        tracing_extra: dict[str, Any],
        logger: Optional[logging.Logger],
    ) -> Any:
        """Send one Responses API request; track, log and report its response even when parsing fails."""
        if response_schema is None:
            response = await client.responses.create(**kwargs)
            self._observe(response, kwargs["input"], tracing_extra, logger)
            return response
        raw = await client.responses.with_raw_response.parse(text_format=response_schema, **kwargs)
        try:
            response = raw.parse()
        except Exception as exc:
            unparsed = self._unparsed_response(raw)
            if unparsed is None:
                self._observe(
                    None, kwargs["input"], {**tracing_extra, "response_error": str(exc)}, logger, response_error=exc
                )
            else:
                self._observe(
                    unparsed, kwargs["input"], {**tracing_extra, "parse_error": str(exc)}, logger, parse_error=exc
                )
            raise
        self._observe(response, kwargs["input"], tracing_extra, logger)
        return response

    @staticmethod
    def _unparsed_response(raw: Any) -> Any:
        """The model response of a request whose structured output failed to parse.

        ``None`` when the HTTP body is not a Responses API payload at all (for example an HTML page
        from a proxy served with status 200): then no model output was received.
        """
        from openai.types.responses import Response

        try:
            body = raw.http_response.json()
        except Exception:  # noqa: BLE001
            return None
        if not isinstance(body, dict) or body.get("object") != "response":
            return None
        try:
            return Response.model_validate(body)
        except Exception:  # noqa: BLE001
            return Response.construct(**body)

    def _observe(
        self,
        response: Any,
        messages: list[Any],
        metadata: dict[str, Any],
        logger: Optional[logging.Logger],
        parse_error: Optional[BaseException] = None,
        response_error: Optional[BaseException] = None,
    ) -> None:
        self.observability.track_llm_call(
            name="openai_responses",
            model=self.model_name,
            messages=messages,
            response=response,
            metadata=metadata,
        )
        self._log_response(response, logger)
        moderation = _moderation(response)
        for side, result in (moderation or {}).items():
            if result.get("flagged"):
                (logger or _logger).warning(
                    f"Moderation flagged the {side} of a {self.model_name} call: {', '.join(result['categories'])}"
                )
        report_llm_call(
            LLMCallRecord(
                provider="openai",
                model=getattr(response, "model", None) or self.model_name,
                finish_reason=_finish_reason(response),
                usage=_usage(response),
                raw_output=_output_text(response),
                parse_error=str(parse_error) if parse_error is not None else None,
                response_error=str(response_error) if response_error is not None else None,
                response_id=_response_id(response),
                messages=list(messages),
                reasoning_summary=_reasoning_summary(response),
                moderation=moderation,
            )
        )

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

        Every provider response is tracked, logged and reported to ``capture_llm_calls`` with its finish
        reason and usage, including one whose structured output fails to parse (for example JSON cut off
        at ``max_output_tokens``); that parse error is then re-raised. A body that is not a Responses API
        payload (for example a proxy's HTML page) is reported with ``response_error`` instead of
        ``parse_error``, and its decoding error is re-raised.

        Raises:
            ImportError: If OpenAI is not installed.
            pydantic.ValidationError: A structured output did not match ``response_schema``.
        """
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=self.api_key, **self._client_options)

            base_kwargs: dict[str, Any] = {
                "model": self.model_name,
                **self._guardrail_kwargs,
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

                response = await self._request(client, response_schema, kwargs, tracing_extra, logger)

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
            response = await self._request(client, response_schema, final_kwargs, tracing_extra, logger)
            return response.output_parsed if response_schema is not None else response.output_text
        except ImportError as e:
            _logger.error(f"Failed to import OpenAI: {e}")
            raise ImportError("OpenAI is not installed. Install it with: pip install econagents[openai]") from e


def _responses_parameters() -> frozenset[str]:
    """The request parameters the installed ``openai`` package's Responses API accepts."""
    from openai.resources.responses import AsyncResponses

    return frozenset(inspect.signature(AsyncResponses.create).parameters)


def _field(value: Any, name: str) -> Any:
    return value.get(name) if isinstance(value, dict) else getattr(value, name, None)


def _moderation(response: Any) -> Optional[dict[str, Any]]:
    """The moderation of a response's input and output as plain data, or ``None`` when it carries none."""
    moderation = _field(response, "moderation")
    record: dict[str, Any] = {}
    for side in ("input", "output"):
        result = _field(moderation, side)
        kind = _field(result, "type")
        if kind == "moderation_result":
            categories = _field(result, "categories") or {}
            record[side] = {
                "flagged": _field(result, "flagged") is True,
                "categories": sorted(name for name, hit in dict(categories).items() if hit is True),
                "category_scores": dict(_field(result, "category_scores") or {}),
                "model": _field(result, "model"),
            }
        elif kind == "error":
            record[side] = {"error": _field(result, "code"), "message": _field(result, "message")}
    return record or None


def _finish_reason(response: Any) -> Optional[str]:
    status = getattr(response, "status", None)
    details = getattr(response, "incomplete_details", None)
    reason = getattr(details, "reason", None)
    if status == "incomplete" and isinstance(reason, str):
        return reason
    return status if isinstance(status, str) else None


def _response_id(response: Any) -> Optional[str]:
    response_id = getattr(response, "id", None)
    return response_id if isinstance(response_id, str) else None


def _usage(response: Any) -> Optional[dict[str, Optional[int]]]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    details = getattr(usage, "output_tokens_details", None)
    return {
        "input_tokens": getattr(usage, "input_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
        "reasoning_tokens": getattr(details, "reasoning_tokens", None),
    }


def _output_text(response: Any) -> Optional[str]:
    texts = [
        getattr(part, "text", None)
        for item in getattr(response, "output", None) or []
        if getattr(item, "type", None) == "message"
        for part in getattr(item, "content", None) or []
        if getattr(part, "type", None) == "output_text"
    ]
    texts = [text for text in texts if isinstance(text, str)]
    if texts:
        return "".join(texts)
    text = getattr(response, "output_text", None)
    return text if isinstance(text, str) and text else None


def _reasoning_summary(response: Any) -> Optional[list[str]]:
    texts = [
        getattr(part, "text", None)
        for item in getattr(response, "output", None) or []
        if getattr(item, "type", None) == "reasoning"
        for part in getattr(item, "summary", None) or []
        if getattr(part, "type", None) == "summary_text"
    ]
    return [text for text in texts if isinstance(text, str)] or None
