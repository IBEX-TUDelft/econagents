from typing import Any, Optional

from langsmith.wrappers import wrap_openai
from openai import AsyncOpenAI


class ChatOpenAI:
    """
    A simple wrapper for LLM queries, e.g. using OpenAI's API.
    """

    def __init__(
        self,
        model_name: str = "gpt-4o",
        api_key: Optional[str] = None,
    ) -> None:
        """Initialize the LLM interface."""
        self.model_name = model_name
        self.client = wrap_openai(AsyncOpenAI(api_key=api_key))

    def build_messages(self, system_prompt: str, user_prompt: str):
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    async def get_response(self, messages: list[dict[str, Any]], **kwargs: Any):
        response = await self.client.chat.completions.create(
            messages=messages,  # type: ignore
            model=self.model_name,
            response_format={"type": "json_object"},
            **kwargs,
        )
        return response.choices[0].message.content
