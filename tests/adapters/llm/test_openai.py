from typing import Literal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from econagents.adapters.llm.openai import ChatOpenAI


class _SampleSchema(BaseModel):
    gameId: int
    action: Literal["go", "stop"]


class TestChatOpenAI:
    """Tests for the ChatOpenAI class."""

    def test_initialization(self):
        """Initializes with sensible defaults."""
        with patch("importlib.util.find_spec", return_value=True):
            openai = ChatOpenAI()

            assert openai.model_name == "gpt-5.4-mini"
            assert openai.api_key is None
            assert openai.reasoning_effort is None
            assert openai.reasoning_summary is None

    def test_initialization_with_parameters(self):
        """Initializes with custom parameters including reasoning settings."""
        with patch("importlib.util.find_spec", return_value=True):
            openai = ChatOpenAI(
                model_name="gpt-4.1-mini",
                api_key="test_api_key",
                reasoning_effort="medium",
                reasoning_summary="auto",
            )

            assert openai.model_name == "gpt-4.1-mini"
            assert openai.api_key == "test_api_key"
            assert openai.reasoning_effort == "medium"
            assert openai.reasoning_summary == "auto"

    def test_check_openai_available_failure(self):
        """Raises ImportError when the openai package is missing."""
        with patch("importlib.util.find_spec", return_value=None):
            with pytest.raises(ImportError) as exc_info:
                ChatOpenAI()

            assert "OpenAI is not installed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_response_without_schema(self):
        """Without a schema the Responses API output text is returned."""
        mock_response = MagicMock()
        mock_response.output_text = "plain response"

        mock_client = MagicMock()
        mock_client.responses.create = AsyncMock(return_value=mock_response)

        with (
            patch("importlib.util.find_spec", return_value=True),
            patch("openai.AsyncOpenAI", return_value=mock_client),
        ):
            openai = ChatOpenAI(model_name="gpt-4.1-mini")
            openai.observability = MagicMock()

            messages = [{"role": "user", "content": "Hello"}]
            response = await openai.get_response(messages, tracing_extra={})

            assert response == "plain response"
            mock_client.responses.create.assert_called_once()
            call_kwargs = mock_client.responses.create.call_args.kwargs
            assert call_kwargs["model"] == "gpt-4.1-mini"
            assert call_kwargs["input"] == messages
            assert "reasoning" not in call_kwargs
            openai.observability.track_llm_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_response_with_schema(self):
        """With a schema the parsed Pydantic instance is returned."""
        parsed = _SampleSchema(gameId=7, action="go")
        mock_response = MagicMock()
        mock_response.output_parsed = parsed

        mock_client = MagicMock()
        mock_client.responses.parse = AsyncMock(return_value=mock_response)

        with (
            patch("importlib.util.find_spec", return_value=True),
            patch("openai.AsyncOpenAI", return_value=mock_client),
        ):
            openai = ChatOpenAI(model_name="gpt-4.1-mini")
            openai.observability = MagicMock()

            messages = [{"role": "user", "content": "Hello"}]
            response = await openai.get_response(
                messages,
                tracing_extra={},
                response_schema=_SampleSchema,
            )

            assert response is parsed
            mock_client.responses.parse.assert_called_once()
            call_kwargs = mock_client.responses.parse.call_args.kwargs
            assert call_kwargs["text_format"] is _SampleSchema
            assert call_kwargs["model"] == "gpt-4.1-mini"
            assert call_kwargs["input"] == messages

    @pytest.mark.asyncio
    async def test_reasoning_forwarded_when_set(self):
        """Reasoning params are only forwarded when configured."""
        mock_response = MagicMock()
        mock_response.output_text = "ok"

        mock_client = MagicMock()
        mock_client.responses.create = AsyncMock(return_value=mock_response)

        with (
            patch("importlib.util.find_spec", return_value=True),
            patch("openai.AsyncOpenAI", return_value=mock_client),
        ):
            openai = ChatOpenAI(
                model_name="gpt-5-mini",
                reasoning_effort="high",
                reasoning_summary="concise",
            )
            openai.observability = MagicMock()

            await openai.get_response([{"role": "user", "content": "hi"}], tracing_extra={})

            call_kwargs = mock_client.responses.create.call_args.kwargs
            assert call_kwargs["reasoning"] == {"effort": "high", "summary": "concise"}

    @pytest.mark.asyncio
    async def test_response_kwargs_forwarded(self):
        """Extra response_kwargs are forwarded to the Responses API."""
        mock_response = MagicMock()
        mock_response.output_text = "ok"

        mock_client = MagicMock()
        mock_client.responses.create = AsyncMock(return_value=mock_response)

        with (
            patch("importlib.util.find_spec", return_value=True),
            patch("openai.AsyncOpenAI", return_value=mock_client),
        ):
            openai = ChatOpenAI(
                model_name="gpt-4.1-mini",
                response_kwargs={"temperature": 0.3, "max_output_tokens": 200},
            )
            openai.observability = MagicMock()

            await openai.get_response([{"role": "user", "content": "hi"}], tracing_extra={})

            call_kwargs = mock_client.responses.create.call_args.kwargs
            assert call_kwargs["temperature"] == 0.3
            assert call_kwargs["max_output_tokens"] == 200

    @pytest.mark.asyncio
    async def test_full_response_logged_when_logger_given(self):
        """The full API response (including reasoning) is logged at DEBUG level."""
        mock_response = MagicMock()
        mock_response.output_text = "ok"
        mock_response.model_dump_json.return_value = '{"output": [{"type": "reasoning", "summary": "because"}]}'

        mock_client = MagicMock()
        mock_client.responses.create = AsyncMock(return_value=mock_response)
        log = MagicMock()

        with (
            patch("importlib.util.find_spec", return_value=True),
            patch("openai.AsyncOpenAI", return_value=mock_client),
        ):
            openai = ChatOpenAI(model_name="gpt-4.1-mini")
            openai.observability = MagicMock()

            await openai.get_response([{"role": "user", "content": "hi"}], tracing_extra={}, logger=log)

        mock_response.model_dump_json.assert_called_once()
        log.debug.assert_called_once()
        logged = log.debug.call_args.args[0]
        assert "LLM RESPONSE" in logged
        assert '"type": "reasoning"' in logged

    @pytest.mark.asyncio
    async def test_response_not_logged_without_logger(self):
        """Without a logger the response is returned but nothing is serialized."""
        mock_response = MagicMock()
        mock_response.output_text = "ok"

        mock_client = MagicMock()
        mock_client.responses.create = AsyncMock(return_value=mock_response)

        with (
            patch("importlib.util.find_spec", return_value=True),
            patch("openai.AsyncOpenAI", return_value=mock_client),
        ):
            openai = ChatOpenAI(model_name="gpt-4.1-mini")
            openai.observability = MagicMock()

            response = await openai.get_response([{"role": "user", "content": "hi"}], tracing_extra={})

        assert response == "ok"
        mock_response.model_dump_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_response_import_error(self):
        """Raises ImportError when the openai package can't be imported at call time."""
        with (
            patch("importlib.util.find_spec", return_value=True),
            patch("openai.AsyncOpenAI", side_effect=ImportError("Module not found")),
        ):
            openai = ChatOpenAI()

            with pytest.raises(ImportError) as exc_info:
                await openai.get_response([{"role": "user", "content": "Hello"}], tracing_extra={})

            assert "OpenAI is not installed" in str(exc_info.value)

    def test_build_messages(self):
        """build_messages returns the canonical system/user pair."""
        with patch("importlib.util.find_spec", return_value=True):
            openai = ChatOpenAI()

            messages = openai.build_messages("You are a helpful assistant.", "Hello")

            assert messages == [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Hello"},
            ]
