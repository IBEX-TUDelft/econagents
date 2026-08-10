from types import SimpleNamespace
from typing import Literal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from econagents.adapters.config import RoleSpec
from econagents.adapters.llm import ChatOpenRouter
from econagents.ports.tools import ToolCall, ToolSpec


class _SampleSchema(BaseModel):
    game_id: int
    action: Literal["go", "stop"]


def _response(content: str, tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class TestChatOpenRouter:
    def test_initialization(self):
        with patch("importlib.util.find_spec", return_value=True):
            llm = ChatOpenRouter(api_key="test-key")

        assert llm.model_name == "openai/gpt-5.4-mini"
        assert llm.api_key == "test-key"
        assert llm.base_url == "https://openrouter.ai/api/v1"

    def test_rejects_two_reasoning_budget_controls(self):
        with (
            patch("importlib.util.find_spec", return_value=True),
            pytest.raises(ValueError, match="cannot be used together"),
        ):
            ChatOpenRouter(api_key="test-key", reasoning_effort="high", reasoning_max_tokens=2000)

    def test_check_client_available_failure(self):
        with (
            patch("importlib.util.find_spec", return_value=None),
            pytest.raises(ImportError, match="requires the OpenAI client"),
        ):
            ChatOpenRouter(api_key="test-key")

    def test_can_be_created_from_yaml_role_spec(self):
        spec = RoleSpec(
            role_id=1,
            name="player",
            llm_type="ChatOpenRouter",
            llm_params={"model_name": "anthropic/claude-sonnet-4", "api_key": "test-key"},
        )

        with patch("importlib.util.find_spec", return_value=True):
            role = spec.create_role()

        assert isinstance(role.llm, ChatOpenRouter)
        assert role.llm.model_name == "anthropic/claude-sonnet-4"

    @pytest.mark.asyncio
    async def test_uses_openrouter_environment_key_and_attribution_headers(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=_response("plain response"))

        with (
            patch("importlib.util.find_spec", return_value=True),
            patch.dict("os.environ", {"OPENROUTER_API_KEY": "env-key"}, clear=True),
            patch("openai.AsyncOpenAI", return_value=mock_client) as client_class,
        ):
            llm = ChatOpenRouter(site_url="https://example.com", app_name="Example Experiment")
            llm.observability = MagicMock()
            result = await llm.get_response([{"role": "user", "content": "Hello"}], tracing_extra={})

        assert result == "plain response"
        client_class.assert_called_once_with(
            api_key="env-key",
            base_url="https://openrouter.ai/api/v1",
            default_headers={
                "HTTP-Referer": "https://example.com",
                "X-OpenRouter-Title": "Example Experiment",
            },
        )
        llm.observability.track_llm_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_missing_api_key_has_provider_specific_error(self):
        with (
            patch("importlib.util.find_spec", return_value=True),
            patch.dict("os.environ", {}, clear=True),
        ):
            llm = ChatOpenRouter()
            with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
                await llm.get_response([{"role": "user", "content": "Hello"}], tracing_extra={})

    @pytest.mark.asyncio
    async def test_structured_output_is_requested_and_validated(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=_response('{"game_id": 7, "action": "go"}'))

        with (
            patch("importlib.util.find_spec", return_value=True),
            patch("openai.AsyncOpenAI", return_value=mock_client),
        ):
            llm = ChatOpenRouter(api_key="test-key")
            llm.observability = MagicMock()
            result = await llm.get_response(
                [{"role": "user", "content": "Choose"}],
                tracing_extra={},
                response_schema=_SampleSchema,
            )

        assert result == _SampleSchema(game_id=7, action="go")
        response_format = mock_client.chat.completions.create.call_args.kwargs["response_format"]
        assert response_format["type"] == "json_schema"
        assert response_format["json_schema"]["strict"] is True
        assert response_format["json_schema"]["schema"]["additionalProperties"] is False
        assert response_format["json_schema"]["schema"]["required"] == ["game_id", "action"]

    @pytest.mark.asyncio
    async def test_reasoning_and_response_kwargs_are_forwarded(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=_response("ok"))

        with (
            patch("importlib.util.find_spec", return_value=True),
            patch("openai.AsyncOpenAI", return_value=mock_client),
        ):
            llm = ChatOpenRouter(
                api_key="test-key",
                reasoning_effort="high",
                reasoning_exclude=True,
                response_kwargs={
                    "temperature": 0.2,
                    "extra_body": {"provider": {"require_parameters": True}},
                },
            )
            llm.observability = MagicMock()
            await llm.get_response([{"role": "user", "content": "Hello"}], tracing_extra={})

        kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert kwargs["temperature"] == 0.2
        assert kwargs["extra_body"] == {
            "provider": {"require_parameters": True},
            "reasoning": {"effort": "high", "exclude": True},
        }

    @pytest.mark.asyncio
    async def test_tool_loop_preserves_reasoning_and_returns_result(self):
        function = SimpleNamespace(name="add", arguments='{"a": 2, "b": 3}')
        call = SimpleNamespace(id="call-1", function=function)
        first_message = SimpleNamespace(
            content=None,
            tool_calls=[call],
            reasoning=None,
            reasoning_details=[{"type": "reasoning.encrypted", "data": "opaque"}],
        )
        first = SimpleNamespace(choices=[SimpleNamespace(message=first_message)])
        second = _response("the sum is 5")

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=[first, second])
        executed: list[ToolCall] = []

        async def executor(tool_call: ToolCall):
            executed.append(tool_call)
            return {"sum": tool_call.arguments["a"] + tool_call.arguments["b"]}

        spec = ToolSpec(
            name="add",
            description="Add two numbers",
            parameters={"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}},
        )

        with (
            patch("importlib.util.find_spec", return_value=True),
            patch("openai.AsyncOpenAI", return_value=mock_client),
        ):
            llm = ChatOpenRouter(api_key="test-key")
            llm.observability = MagicMock()
            result = await llm.get_response(
                [{"role": "user", "content": "Add 2 and 3"}],
                tracing_extra={},
                tools=[spec],
                tool_executor=executor,
            )

        assert result == "the sum is 5"
        assert executed == [ToolCall(id="call-1", name="add", arguments={"a": 2, "b": 3})]
        first_kwargs = mock_client.chat.completions.create.call_args_list[0].kwargs
        assert first_kwargs["tools"][0]["function"]["name"] == "add"

        conversation = mock_client.chat.completions.create.call_args_list[1].kwargs["messages"]
        assert conversation[1]["reasoning_details"] == [{"type": "reasoning.encrypted", "data": "opaque"}]
        assert conversation[2] == {
            "role": "tool",
            "tool_call_id": "call-1",
            "name": "add",
            "content": '{"sum": 5}',
        }

    @pytest.mark.asyncio
    async def test_get_response_import_error(self):
        with (
            patch("importlib.util.find_spec", return_value=True),
            patch("openai.AsyncOpenAI", side_effect=ImportError("missing")),
        ):
            llm = ChatOpenRouter(api_key="test-key")
            with pytest.raises(ImportError, match="requires the OpenAI client"):
                await llm.get_response([{"role": "user", "content": "Hello"}], tracing_extra={})
