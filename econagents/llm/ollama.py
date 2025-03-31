import importlib.util
import json
import logging
from typing import Any, Dict, List, Optional

from econagents.llm.base import BaseLLM

logger = logging.getLogger(__name__)


class ChatOllama(BaseLLM):
    """A wrapper for LLM queries using Ollama."""

    def __init__(
        self,
        model_name: str,
        host: Optional[str] = None,
    ) -> None:
        """Initialize the Ollama LLM interface.

        Args:
            model_name: The model name to use.
            host: The host for the Ollama API (e.g., "http://localhost:11434").
        """
        self._check_ollama_available()
        self.model_name = model_name
        self.host = host

    def _check_ollama_available(self) -> None:
        """Check if Ollama is available."""
        if not importlib.util.find_spec("ollama"):
            raise ImportError("Ollama is not installed. Install it with: pip install econagents[ollama]")

    async def get_response(
        self,
        messages: List[Dict[str, Any]],
        tracing_extra: Dict[str, Any],
        **kwargs: Any,
    ) -> str:
        """Get a response from the LLM.

        Args:
            messages: The messages for the LLM.
            tracing_extra: The extra tracing information.
            **kwargs: Additional arguments to pass to the LLM.

        Returns:
            The response from the LLM.

        Raises:
            ImportError: If Ollama is not installed.
        """
        try:
            from ollama import AsyncClient

            client = AsyncClient(host=self.host)

            response = await client.chat(
                model=self.model_name,
                messages=messages,
                **kwargs,
            )

            # End the LLM run
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
