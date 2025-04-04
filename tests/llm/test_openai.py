import importlib.util
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from econagents.llm.openai import ChatOpenAI


class TestChatOpenAI:
    """Tests for the ChatOpenAI class."""

    def test_initialization(self):
        """Test that the OpenAI LLM initializes correctly with default parameters."""
        with patch("importlib.util.find_spec", return_value=True):
            openai = ChatOpenAI()

            assert openai.model_name == "gpt-4o"
            assert openai.api_key is None

    def test_initialization_with_parameters(self):
        """Test that the OpenAI LLM initializes correctly with custom parameters."""
        with patch("importlib.util.find_spec", return_value=True):
            openai = ChatOpenAI(model_name="gpt-3.5-turbo", api_key="test_api_key")

            assert openai.model_name == "gpt-3.5-turbo"
            assert openai.api_key == "test_api_key"

    def test_check_openai_available_success(self):
        """Test that _check_openai_available doesn't raise an error when OpenAI is available."""
        with patch("importlib.util.find_spec", return_value=True):
            openai = ChatOpenAI()
            # Should not raise an exception
            openai._check_openai_available()

    def test_check_openai_available_failure(self):
        """Test that _check_openai_available raises an error when OpenAI is not available."""
        with patch("importlib.util.find_spec", return_value=None):
            with pytest.raises(ImportError) as exc_info:
                ChatOpenAI()

            assert "OpenAI is not installed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_response(self):
        """Test getting a response from the OpenAI LLM."""
        # Create mock response
        mock_message = MagicMock()
        mock_message.content = "test response"

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        # Create mock client
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with (
            patch("importlib.util.find_spec", return_value=True),
            patch("openai.AsyncOpenAI", return_value=mock_client),
        ):
            openai = ChatOpenAI(model_name="gpt-4o")
            openai.observability = MagicMock()

            messages = [{"role": "user", "content": "Hello"}]
            response = await openai.get_response(messages, tracing_extra={})

            assert response == "test response"
            mock_client.chat.completions.create.assert_called_once()
            assert mock_client.chat.completions.create.call_args[1]["model"] == "gpt-4o"
            assert mock_client.chat.completions.create.call_args[1]["messages"] == messages
            openai.observability.track_llm_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_response_with_additional_params(self):
        """Test getting a response from the OpenAI LLM with additional parameters."""
        # Create mock response
        mock_message = MagicMock()
        mock_message.content = "test response"

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        # Create mock client
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with (
            patch("importlib.util.find_spec", return_value=True),
            patch("openai.AsyncOpenAI", return_value=mock_client),
        ):
            openai = ChatOpenAI(model_name="gpt-4o")
            openai.observability = MagicMock()

            messages = [{"role": "user", "content": "Hello"}]
            await openai.get_response(messages, tracing_extra={}, temperature=0.7, max_tokens=100)

            assert mock_client.chat.completions.create.call_args[1]["temperature"] == 0.7
            assert mock_client.chat.completions.create.call_args[1]["max_tokens"] == 100

    @pytest.mark.asyncio
    async def test_get_response_import_error(self):
        """Test that get_response raises an error when OpenAI is not available."""
        with (
            patch("importlib.util.find_spec", return_value=True),
            patch("openai.AsyncOpenAI", side_effect=ImportError("Module not found")),
        ):
            openai = ChatOpenAI()

            messages = [{"role": "user", "content": "Hello"}]
            with pytest.raises(ImportError) as exc_info:
                await openai.get_response(messages, tracing_extra={})

            assert "OpenAI is not installed" in str(exc_info.value)

    def test_build_messages(self):
        """Test building messages for the LLM."""
        with patch("importlib.util.find_spec", return_value=True):
            openai = ChatOpenAI()

            system_prompt = "You are a helpful assistant."
            user_prompt = "Hello, can you help me?"

            messages = openai.build_messages(system_prompt, user_prompt)

            assert len(messages) == 2
            assert messages[0]["role"] == "system"
            assert messages[0]["content"] == system_prompt
            assert messages[1]["role"] == "user"
            assert messages[1]["content"] == user_prompt
