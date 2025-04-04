import importlib.util
import logging
from typing import Any, Optional

from econagents.llm.base import BaseLLM

logger = logging.getLogger(__name__)


class ChatOpenAI(BaseLLM):
    """A wrapper for LLM queries using OpenAI."""

    def __init__(
        self,
        model_name: str = "gpt-4o",
        api_key: Optional[str] = None,
    ) -> None:
        """Initialize the OpenAI LLM interface.

        Args:
            model_name: The model name to use.
            api_key: The API key to use for authentication.
        """
        self.model_name = model_name
        self.api_key = api_key
        self._check_openai_available()

    def _check_openai_available(self) -> None:
        """Check if OpenAI is available."""
        if not importlib.util.find_spec("openai"):
            raise ImportError("OpenAI is not installed. Install it with: pip install econagents[openai]")

    async def get_response(
        self,
        messages: list[dict[str, Any]],
        tracing_extra: dict[str, Any],
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
            ImportError: If OpenAI is not installed.
        """
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=self.api_key)

            # Create OpenAI completion
            response = await client.chat.completions.create(
                model=self.model_name,
                messages=messages,  # type: ignore
                response_format={"type": "json_object"},
                **kwargs,
            )

            # Track the LLM call using the observability provider
            self.observability.track_llm_call(
                name="openai_chat_completion",
                model=self.model_name,
                messages=messages,
                response=response,
                metadata=tracing_extra,
            )

            return response.choices[0].message.content
        except ImportError as e:
            logger.error(f"Failed to import OpenAI: {e}")
            raise ImportError("OpenAI is not installed. Install it with: pip install econagents[openai]") from e
