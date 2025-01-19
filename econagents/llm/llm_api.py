from typing import Any, Optional

import openai
from openai import OpenAI


class LLMInterface:
    """
    A simple wrapper for LLM queries, e.g. using OpenAI's API.
    """

    def __init__(
        self,
        api_key: str,
        model_name: str = "gpt-4o-mini",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> None:
        """Initialize the LLM interface."""
        self.model_name = model_name
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.client = OpenAI(api_key=api_key)

    def get_response(self, *args, **kwargs):
        pass
