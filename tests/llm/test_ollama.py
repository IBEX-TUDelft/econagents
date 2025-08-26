import importlib.util
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from econagents.llm.ollama import ChatOllama


class TestChatOllama:
    """Tests for the ChatOllama class."""

    def test_initialization(self):
        """Test that the Ollama LLM initializes correctly."""
        with patch("importlib.util.find_spec", return_value=True):
            ollama = ChatOllama(model_name="llama2")

            assert ollama.model_name == "llama2"
            assert ollama.host is None

    def test_initialization_with_host(self):
        """Test that the Ollama LLM initializes correctly with a host."""
        with patch("importlib.util.find_spec", return_value=True):
            ollama = ChatOllama(model_name="llama2", host="http://localhost:11434")

            assert ollama.model_name == "llama2"
            assert ollama.host == "http://localhost:11434"

    def test_check_ollama_available_success(self):
        """Test that _check_ollama_available doesn't raise an error when Ollama is available."""
        with patch("importlib.util.find_spec", return_value=True):
            ollama = ChatOllama(model_name="llama2")
            # Should not raise an exception
            ollama._check_ollama_available()

    def test_check_ollama_available_failure(self):
        """Test that _check_ollama_available raises an error when Ollama is not available."""
        with patch("importlib.util.find_spec", return_value=None):
            with pytest.raises(ImportError) as exc_info:
                ChatOllama(model_name="llama2")

            assert "Ollama is not installed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_response(self):
        """Test getting a response from the Ollama LLM."""
        mock_client = AsyncMock()
        mock_client.chat.return_value = {"message": {"content": "test response"}}

        with (
            patch("importlib.util.find_spec", return_value=True),
            patch("ollama.AsyncClient", return_value=mock_client),
        ):
            ollama = ChatOllama(model_name="llama2")
            ollama.observability = MagicMock()

            messages = [{"role": "user", "content": "Hello"}]
            response = await ollama.get_response(messages, tracing_extra={})

            assert response == "test response"
            mock_client.chat.assert_called_once_with(model="llama2", messages=messages)
            ollama.observability.track_llm_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_response_with_additional_params(self):
        """Test getting a response from the Ollama LLM with additional parameters."""
        mock_client = AsyncMock()
        mock_client.chat.return_value = {"message": {"content": "test response"}}

        with (
            patch("importlib.util.find_spec", return_value=True),
            patch("ollama.AsyncClient", return_value=mock_client),
        ):
            ollama = ChatOllama(
                model_name="llama2",
                response_kwargs={"temperature": 0.7, "num_predict": 100}
            )
            ollama.observability = MagicMock()

            messages = [{"role": "user", "content": "Hello"}]
            response = await ollama.get_response(messages, tracing_extra={})

            assert response == "test response"
            mock_client.chat.assert_called_once_with(
                model="llama2", 
                messages=messages, 
                temperature=0.7, 
                num_predict=100
            )
            ollama.observability.track_llm_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_response_import_error(self):
        """Test that get_response raises an error when Ollama is not available."""
        with (
            patch("importlib.util.find_spec", return_value=True),
            patch("ollama.AsyncClient", side_effect=ImportError("Module not found")),
        ):
            ollama = ChatOllama(model_name="llama2")

            messages = [{"role": "user", "content": "Hello"}]
            with pytest.raises(ImportError) as exc_info:
                await ollama.get_response(messages, tracing_extra={})

            assert "Ollama is not installed" in str(exc_info.value)

    def test_build_messages(self):
        """Test building messages for the LLM."""
        with patch("importlib.util.find_spec", return_value=True):
            ollama = ChatOllama(model_name="llama2")

            system_prompt = "You are a helpful assistant."
            user_prompt = "Hello, can you help me?"

            messages = ollama.build_messages(system_prompt, user_prompt)

            assert len(messages) == 2
            assert messages[0]["role"] == "system"
            assert messages[0]["content"] == system_prompt
            assert messages[1]["role"] == "user"
            assert messages[1]["content"] == user_prompt
