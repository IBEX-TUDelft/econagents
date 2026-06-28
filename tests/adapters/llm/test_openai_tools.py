from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from econagents.adapters.llm.openai import ChatOpenAI
from econagents.ports.tools import ToolCall, ToolSpec


def _function_call(call_id: str, name: str, arguments: str):
    item = MagicMock()
    item.type = "function_call"
    item.call_id = call_id
    item.name = name
    item.arguments = arguments
    return item


SPEC = ToolSpec(
    name="add",
    description="Add two numbers",
    parameters={"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}},
)


class TestChatOpenAIToolLoop:
    @pytest.mark.asyncio
    async def test_runs_tool_then_returns_final_text(self):
        """The adapter executes a requested tool call and feeds the result back."""
        first = MagicMock()
        first.output = [_function_call("call_1", "add", '{"a": 2, "b": 3}')]
        second = MagicMock()
        second.output = []
        second.output_text = "the sum is 5"

        mock_client = MagicMock()
        mock_client.responses.create = AsyncMock(side_effect=[first, second])

        executed = []

        async def executor(call: ToolCall):
            executed.append(call)
            return {"sum": call.arguments["a"] + call.arguments["b"]}

        with (
            patch("importlib.util.find_spec", return_value=True),
            patch("openai.AsyncOpenAI", return_value=mock_client),
        ):
            llm = ChatOpenAI(model_name="gpt-4.1-mini")
            llm.observability = MagicMock()

            result = await llm.get_response(
                [{"role": "user", "content": "add 2 and 3"}],
                tracing_extra={},
                tools=[SPEC],
                tool_executor=executor,
            )

        assert result == "the sum is 5"
        assert len(executed) == 1
        assert executed[0].name == "add"
        assert executed[0].arguments == {"a": 2, "b": 3}

        # Second call must include the function_call + function_call_output items.
        second_input = mock_client.responses.create.call_args_list[1].kwargs["input"]
        assert any(i.get("type") == "function_call" for i in second_input if isinstance(i, dict))
        output_item = next(i for i in second_input if isinstance(i, dict) and i.get("type") == "function_call_output")
        assert output_item["call_id"] == "call_1"
        assert '"sum": 5' in output_item["output"]
        # Tools advertised on the request.
        assert mock_client.responses.create.call_args_list[0].kwargs["tools"][0]["name"] == "add"

    @pytest.mark.asyncio
    async def test_no_tools_keeps_single_shot_path(self):
        """Without tools the adapter makes exactly one call and returns text."""
        resp = MagicMock()
        resp.output_text = "plain"

        mock_client = MagicMock()
        mock_client.responses.create = AsyncMock(return_value=resp)

        with (
            patch("importlib.util.find_spec", return_value=True),
            patch("openai.AsyncOpenAI", return_value=mock_client),
        ):
            llm = ChatOpenAI(model_name="gpt-4.1-mini")
            llm.observability = MagicMock()

            result = await llm.get_response([{"role": "user", "content": "hi"}], tracing_extra={})

        assert result == "plain"
        mock_client.responses.create.assert_called_once()
        assert "tools" not in mock_client.responses.create.call_args.kwargs

    @pytest.mark.asyncio
    async def test_stops_at_max_iterations(self):
        """A model that never stops calling tools is capped and forced to answer."""
        looping = MagicMock()
        looping.output = [_function_call("c", "add", "{}")]
        final = MagicMock()
        final.output_text = "forced"

        mock_client = MagicMock()
        # Every looped call returns a tool request; the final forced call returns text.
        mock_client.responses.create = AsyncMock(side_effect=[looping, looping, final])

        async def executor(call: ToolCall):
            return {"ok": True}

        with (
            patch("importlib.util.find_spec", return_value=True),
            patch("openai.AsyncOpenAI", return_value=mock_client),
        ):
            llm = ChatOpenAI(model_name="gpt-4.1-mini")
            llm.observability = MagicMock()

            result = await llm.get_response(
                [{"role": "user", "content": "go"}],
                tracing_extra={},
                tools=[SPEC],
                tool_executor=executor,
                max_tool_iterations=1,
            )

        assert result == "forced"
        # 1 loop iteration + 1 loop iteration (still calling) + 1 forced final = 3 calls.
        assert mock_client.responses.create.call_count == 3
        # The forced call drops tools.
        assert "tools" not in mock_client.responses.create.call_args_list[-1].kwargs
