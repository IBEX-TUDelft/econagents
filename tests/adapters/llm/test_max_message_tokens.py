import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from econagents.adapters.llm import ChatOpenAI, ChatOpenRouter
from econagents.adapters.llm.ollama import ChatOllama
from econagents.ports.tools import ToolCall, ToolSpec

ADAPTERS = [
    pytest.param(ChatOpenAI, {}, id="openai"),
    pytest.param(ChatOpenRouter, {"api_key": "test-key"}, id="openrouter"),
    pytest.param(ChatOllama, {"model_name": "llama2"}, id="ollama"),
]

SYSTEM_PROMPT = "You are a trader in a market."
USER_PROMPT = "The chat so far: " + "buy now! " * 20


def _find_spec_without_tiktoken(name, *args, **kwargs):
    return None if name == "tiktoken" else True


def _create(adapter, kwargs, **extra):
    with patch("importlib.util.find_spec", return_value=True):
        return adapter(**kwargs, **extra)


@pytest.mark.parametrize("adapter, kwargs", ADAPTERS)
class TestMaxMessageTokens:
    """Tests for the ``max_message_tokens`` setting, with the one-token-per-byte encoding of ``byte_tokenizer``."""

    def test_default_sends_messages_whole_and_needs_no_tiktoken(self, byte_tokenizer, adapter, kwargs):
        with patch("importlib.util.find_spec", side_effect=_find_spec_without_tiktoken):
            llm = adapter(**kwargs)
            messages = llm.build_messages(SYSTEM_PROMPT, USER_PROMPT)

        assert llm.max_message_tokens is None
        assert messages == [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT},
        ]
        assert byte_tokenizer == []

    def test_each_message_is_cut_to_the_limit(self, byte_tokenizer, adapter, kwargs):
        llm = _create(adapter, kwargs, max_message_tokens=12)

        messages = llm.build_messages(SYSTEM_PROMPT, USER_PROMPT)

        assert llm.max_message_tokens == 12
        assert messages == [
            {"role": "system", "content": "You are a tr"},
            {"role": "user", "content": "The chat so "},
        ]

    def test_message_within_the_limit_is_not_changed(self, byte_tokenizer, caplog, adapter, kwargs):
        llm = _create(adapter, kwargs, max_message_tokens=len(USER_PROMPT))

        with caplog.at_level(logging.WARNING):
            messages = llm.build_messages(SYSTEM_PROMPT, USER_PROMPT)

        assert messages[0]["content"] is SYSTEM_PROMPT
        assert messages[1]["content"] is USER_PROMPT
        assert caplog.records == []

    def test_trimmed_message_is_logged_as_a_warning_without_its_text(self, byte_tokenizer, caplog, adapter, kwargs):
        llm = _create(adapter, kwargs, max_message_tokens=50)

        with caplog.at_level(logging.WARNING):
            llm.build_messages(SYSTEM_PROMPT, USER_PROMPT)

        assert [(r.name, r.levelname, r.getMessage()) for r in caplog.records] == [
            ("econagents.adapters.llm.base", "WARNING", "user message trimmed from 197 to 50 tokens"),
        ]

    def test_both_trimmed_messages_are_logged(self, byte_tokenizer, caplog, adapter, kwargs):
        llm = _create(adapter, kwargs, max_message_tokens=12)

        with caplog.at_level(logging.WARNING):
            llm.build_messages(SYSTEM_PROMPT, USER_PROMPT)

        assert [r.getMessage() for r in caplog.records] == [
            "system message trimmed from 29 to 12 tokens",
            "user message trimmed from 197 to 12 tokens",
        ]

    @pytest.mark.parametrize("value", [0, -1, 2.5, "100", True])
    def test_invalid_limit_raises_at_construction(self, byte_tokenizer, adapter, kwargs, value):
        with pytest.raises(ValueError, match="max_message_tokens must be a positive integer"):
            _create(adapter, kwargs, max_message_tokens=value)

    def test_missing_tiktoken_raises_at_construction(self, byte_tokenizer, adapter, kwargs):
        with (
            patch("importlib.util.find_spec", side_effect=_find_spec_without_tiktoken),
            pytest.raises(ImportError, match=r"max_message_tokens needs tiktoken.*pip install econagents\[tokens\]"),
        ):
            adapter(**kwargs, max_message_tokens=100)

        assert byte_tokenizer == []


@pytest.mark.parametrize(
    "adapter, kwargs, encoding",
    [
        pytest.param(ChatOpenAI, {"model_name": "gpt-4"}, "cl100k_base", id="openai-known-model"),
        pytest.param(ChatOpenAI, {"model_name": "my-fine-tune"}, "o200k_base", id="openai-unknown-model"),
        pytest.param(ChatOpenRouter, {"model_name": "anthropic/claude-sonnet-4"}, "o200k_base", id="openrouter"),
        pytest.param(ChatOllama, {"model_name": "llama2"}, "o200k_base", id="ollama"),
    ],
)
def test_tokenizer_of_the_model_is_loaded_at_construction(byte_tokenizer, adapter, kwargs, encoding):
    llm = _create(adapter, kwargs, max_message_tokens=100)

    assert byte_tokenizer == [encoding]

    llm.build_messages(SYSTEM_PROMPT, USER_PROMPT)

    assert byte_tokenizer == [encoding]


@pytest.mark.asyncio
async def test_tool_results_and_model_output_are_not_trimmed(byte_tokenizer):
    tool_result = {"orders": ["buy 10 at 5.00"] * 10}
    answer = "I sell, because the order book is full of buy orders."
    mock_client = AsyncMock()
    mock_client.chat.side_effect = [
        {"message": {"content": "", "tool_calls": [{"function": {"name": "order_book", "arguments": {}}}]}},
        {"message": {"content": answer}},
    ]

    async def executor(tool_call: ToolCall):
        return tool_result

    with (
        patch("importlib.util.find_spec", return_value=True),
        patch("ollama.AsyncClient", return_value=mock_client),
    ):
        llm = ChatOllama(model_name="llama2", max_message_tokens=12)
        llm.observability = MagicMock()
        messages = llm.build_messages(SYSTEM_PROMPT, USER_PROMPT)
        response = await llm.get_response(
            messages,
            tracing_extra={},
            tools=[ToolSpec(name="order_book", description="Read the order book", parameters={"type": "object"})],
            tool_executor=executor,
        )

    assert response == answer
    conversation = mock_client.chat.call_args_list[1].kwargs["messages"]
    assert conversation[:2] == [
        {"role": "system", "content": "You are a tr"},
        {"role": "user", "content": "The chat so "},
    ]
    assert conversation[-1] == {"role": "tool", "tool_name": "order_book", "content": json.dumps(tool_result)}
