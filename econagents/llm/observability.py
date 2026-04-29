"""Observability interfaces for LLM providers."""

import importlib.util
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ObservabilityProvider(ABC):
    """Base class for observability providers."""

    @abstractmethod
    def track_llm_call(
        self,
        name: str,
        model: str,
        messages: List[Dict[str, Any]],
        response: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Track an LLM call.

        Args:
            name: Name of the operation.
            model: Model used for the call.
            messages: Messages sent to the model.
            response: Raw response object from the provider SDK.
            metadata: Additional metadata for the call.
        """
        ...


class NoOpObservability(ObservabilityProvider):
    """No-op observability provider that does nothing."""

    def track_llm_call(
        self,
        name: str,
        model: str,
        messages: List[Dict[str, Any]],
        response: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        pass


def _extract_output(response: Any) -> Any:
    """Best-effort extraction of the user-facing output from a provider response.

    Supports the OpenAI Responses API (``output_parsed``/``output_text``), the
    legacy Chat Completions API (``choices[0].message.content``), and Ollama's
    ``{"message": {"content": ...}}`` dict shape. Falls back to returning the
    raw object.
    """
    parsed = getattr(response, "output_parsed", None)
    if parsed is not None:
        try:
            return parsed.model_dump()
        except AttributeError:
            return parsed

    text = getattr(response, "output_text", None)
    if text:
        return text

    choices = getattr(response, "choices", None)
    if choices:
        first = choices[0]
        message = getattr(first, "message", None)
        content = getattr(message, "content", None) if message is not None else None
        if content is not None:
            return content

    if isinstance(response, dict):
        message = response.get("message")
        if isinstance(message, dict) and "content" in message:
            return message["content"]

    return response


def _extract_usage(response: Any) -> Optional[Dict[str, int]]:
    """Best-effort usage extraction (token counts) from a provider response."""
    usage = getattr(response, "usage", None)
    if usage is None and isinstance(response, dict):
        usage = response.get("usage")
    if usage is None:
        return None

    def _get(name: str) -> Optional[int]:
        val = getattr(usage, name, None)
        if val is None and isinstance(usage, dict):
            val = usage.get(name)
        return val

    input_tokens = _get("input_tokens") or _get("prompt_tokens") or _get("prompt_eval_count")
    output_tokens = _get("output_tokens") or _get("completion_tokens") or _get("eval_count")
    total_tokens = _get("total_tokens")
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens

    details: Dict[str, int] = {}
    if input_tokens is not None:
        details["input"] = int(input_tokens)
    if output_tokens is not None:
        details["output"] = int(output_tokens)
    if total_tokens is not None:
        details["total"] = int(total_tokens)
    return details or None


class LangSmithObservability(ObservabilityProvider):
    """LangSmith observability provider."""

    def __init__(self) -> None:
        self._check_langsmith_available()

    def _check_langsmith_available(self) -> None:
        if not importlib.util.find_spec("langsmith"):
            raise ImportError("LangSmith is not installed. Install it with: pip install econagents[langsmith]")

    def track_llm_call(
        self,
        name: str,
        model: str,
        messages: List[Dict[str, Any]],
        response: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        try:
            from langsmith.run_trees import RunTree

            meta = dict(metadata or {})
            run_tree = RunTree(
                name=name,
                run_type="chain",
                inputs={"messages": messages},
                extra={"metadata": meta, "invocation_params": {"model": model}},
            )
            run_tree.post()

            child_run = run_tree.create_child(
                name=f"{model}",
                run_type="llm",
                inputs={"messages": messages},
                extra={"metadata": meta, "invocation_params": {"model": model}},
            )
            child_run.post()

            output = _extract_output(response)
            usage = _extract_usage(response)
            child_outputs: Dict[str, Any] = {"output": output}
            if usage:
                child_outputs["usage"] = usage

            child_run.end(outputs=child_outputs)
            child_run.patch()

            run_tree.end(outputs={"output": output})
            run_tree.patch()
        except Exception as e:
            logger.warning(f"Failed to track LLM call with LangSmith: {e}")


class LangFuseObservability(ObservabilityProvider):
    """LangFuse observability provider (SDK v4)."""

    def __init__(self) -> None:
        self._check_langfuse_available()
        self._langfuse_client: Optional[Any] = None

    def _check_langfuse_available(self) -> None:
        if not importlib.util.find_spec("langfuse"):
            raise ImportError("LangFuse is not installed. Install it with: pip install econagents[langfuse]")

    def _get_langfuse_client(self) -> Any:
        if self._langfuse_client is None:
            try:
                from langfuse import Langfuse

                self._langfuse_client = Langfuse()
            except ImportError:
                logger.warning("LangFuse is not available.")
                return None
        return self._langfuse_client

    def track_llm_call(
        self,
        name: str,
        model: str,
        messages: List[Dict[str, Any]],
        response: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        client = self._get_langfuse_client()
        if client is None:
            return

        try:
            meta = dict(metadata or {})
            model_parameters = meta.pop("model_parameters", None)

            generation = client.start_observation(
                name=name,
                as_type="generation",
                model=model,
                input=messages,
                metadata=meta or None,
                model_parameters=model_parameters,
            )

            output = _extract_output(response)
            usage_details = _extract_usage(response)

            generation.update(
                output=output,
                usage_details=usage_details,
            )
            generation.end()

            client.flush()
        except Exception as e:
            logger.warning(f"Failed to track LLM call with LangFuse: {e}")


def get_observability_provider(provider_name: str = "noop") -> ObservabilityProvider:
    """Get an observability provider by name.

    Args:
        provider_name: The name of the provider to get.
                      Options: "noop", "langsmith", "langfuse"

    Returns:
        An observability provider.

    Raises:
        ValueError: If the provider_name is invalid.
    """
    if provider_name == "noop":
        return NoOpObservability()
    if provider_name == "langsmith":
        try:
            return LangSmithObservability()
        except ImportError as e:
            logger.warning(f"Failed to initialize LangSmith: {e}")
            logger.warning("Falling back to NoOpObservability")
            return NoOpObservability()
    if provider_name == "langfuse":
        try:
            return LangFuseObservability()
        except ImportError as e:
            logger.warning(f"Failed to initialize LangFuse: {e}")
            logger.warning("Falling back to NoOpObservability")
            return NoOpObservability()
    raise ValueError(f"Invalid observability provider: {provider_name}")
