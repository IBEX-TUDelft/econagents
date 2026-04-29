import importlib.util
import logging
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel

from econagents.llm.base import BaseLLM

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

    async def get_response(
        self,
        messages: List[Dict[str, Any]],
        tracing_extra: Dict[str, Any],
        response_schema: Optional[Type[BaseModel]] = None,
    ) -> str:
        """Get a response from Ollama.

        Args:
            messages: The messages for the LLM.
            tracing_extra: The extra tracing information.
            response_schema: Optional Pydantic model. When provided, its JSON
                schema is passed to Ollama via ``format`` so the local model
                is guided to emit matching JSON. The raw string is still
                returned; the agent layer handles validation.

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

            response = await client.chat(
                model=self.model_name,
                messages=messages,
                **kwargs,
            )

            self.observability.track_llm_call(
                name="ollama_chat_completion",
                model=self.model_name,
                messages=messages,
                response=response,
                metadata=tracing_extra,
            )

            return response["message"]["content"]

        except ImportError as e:
            logger.error(f"Failed to import Ollama: {e}")
            raise ImportError("Ollama is not installed. Install it with: pip install econagents[ollama]") from e
