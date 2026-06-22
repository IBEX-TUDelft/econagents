from unittest.mock import MagicMock, patch

import pytest

from econagents.adapters.llm.observability import (
    LangFuseObservability,
    LangSmithObservability,
    NoOpObservability,
    ObservabilityProvider,
    _extract_output,
    _extract_usage,
    get_observability_provider,
)


class TestObservabilityProviders:
    """Tests for the observability providers."""

    def test_noop_observability(self):
        provider = NoOpObservability()
        # Should not raise any exceptions
        provider.track_llm_call(name="test", model="test-model", messages=[], response={}, metadata={})

    @patch("importlib.util.find_spec")
    def test_langsmith_observability_initialization(self, mock_find_spec):
        mock_find_spec.return_value = True
        provider = LangSmithObservability()
        assert isinstance(provider, ObservabilityProvider)

        mock_find_spec.return_value = None
        with pytest.raises(ImportError) as exc_info:
            LangSmithObservability()
        assert "LangSmith is not installed" in str(exc_info.value)

    @patch("importlib.util.find_spec")
    def test_langfuse_observability_initialization(self, mock_find_spec):
        mock_find_spec.return_value = True
        provider = LangFuseObservability()
        assert isinstance(provider, ObservabilityProvider)

        mock_find_spec.return_value = None
        with pytest.raises(ImportError) as exc_info:
            LangFuseObservability()
        assert "LangFuse is not installed" in str(exc_info.value)

    def test_langsmith_track_llm_call(self):
        with patch("importlib.util.find_spec", return_value=True):
            provider = LangSmithObservability()

            mock_run = MagicMock()
            mock_child = MagicMock()
            mock_run.create_child.return_value = mock_child

            mock_response = MagicMock()
            mock_response.output_text = "response"
            mock_response.output_parsed = None
            mock_response.choices = None
            mock_response.usage = None

            with patch("langsmith.run_trees.RunTree", return_value=mock_run):
                provider.track_llm_call(
                    name="test_call",
                    model="test-model",
                    messages=[{"role": "user", "content": "Hello"}],
                    response=mock_response,
                    metadata={"test": "metadata"},
                )

            mock_run.post.assert_called_once()
            mock_run.create_child.assert_called_once()
            mock_child.post.assert_called_once()
            mock_child.end.assert_called_once()
            mock_child.patch.assert_called_once()
            mock_run.end.assert_called_once()
            mock_run.patch.assert_called_once()

    def test_langsmith_track_llm_call_swallows_errors(self):
        with patch("importlib.util.find_spec", return_value=True):
            provider = LangSmithObservability()

            with patch("langsmith.run_trees.RunTree", side_effect=RuntimeError("boom")):
                # Should log a warning but not raise
                provider.track_llm_call(
                    name="test_call",
                    model="test-model",
                    messages=[],
                    response={},
                    metadata={},
                )

    def test_langfuse_track_llm_call(self):
        with patch("importlib.util.find_spec", return_value=True):
            provider = LangFuseObservability()

            mock_generation = MagicMock()
            mock_client = MagicMock()
            mock_client.start_observation.return_value = mock_generation
            provider._langfuse_client = mock_client

            mock_response = MagicMock()
            mock_response.output_text = "test response"
            mock_response.output_parsed = None
            mock_response.choices = None
            mock_response.usage = None

            provider.track_llm_call(
                name="test_call",
                model="test-model",
                messages=[{"role": "user", "content": "Hello"}],
                response=mock_response,
                metadata={"test": "metadata"},
            )

            mock_client.start_observation.assert_called_once()
            kwargs = mock_client.start_observation.call_args.kwargs
            assert kwargs["as_type"] == "generation"
            assert kwargs["model"] == "test-model"
            mock_generation.update.assert_called_once()
            mock_generation.end.assert_called_once()
            mock_client.flush.assert_called_once()

    def test_langfuse_track_llm_call_swallows_errors(self):
        with patch("importlib.util.find_spec", return_value=True):
            provider = LangFuseObservability()
            mock_client = MagicMock()
            mock_client.start_observation.side_effect = RuntimeError("boom")
            provider._langfuse_client = mock_client

            # Should not raise
            provider.track_llm_call(name="n", model="m", messages=[], response={}, metadata=None)

    def test_get_observability_provider_noop(self):
        provider = get_observability_provider("noop")
        assert isinstance(provider, NoOpObservability)

    @patch("econagents.adapters.llm.observability.LangSmithObservability")
    def test_get_observability_provider_langsmith(self, mock_langsmith):
        get_observability_provider("langsmith")
        mock_langsmith.assert_called_once()

        mock_langsmith.side_effect = ImportError("Test error")
        provider = get_observability_provider("langsmith")
        assert isinstance(provider, NoOpObservability)

    @patch("econagents.adapters.llm.observability.LangFuseObservability")
    def test_get_observability_provider_langfuse(self, mock_langfuse):
        get_observability_provider("langfuse")
        mock_langfuse.assert_called_once()

        mock_langfuse.side_effect = ImportError("Test error")
        provider = get_observability_provider("langfuse")
        assert isinstance(provider, NoOpObservability)

    def test_get_observability_provider_invalid(self):
        with pytest.raises(ValueError) as exc_info:
            get_observability_provider("invalid")
        assert "Invalid observability provider" in str(exc_info.value)


class TestExtractHelpers:
    """Helpers that normalize provider response shapes."""

    def test_extract_output_responses_api_parsed(self):
        class Parsed:
            def model_dump(self):
                return {"ok": True}

        response = MagicMock()
        response.output_parsed = Parsed()
        assert _extract_output(response) == {"ok": True}

    def test_extract_output_responses_api_text(self):
        response = MagicMock()
        response.output_parsed = None
        response.output_text = "hello"
        assert _extract_output(response) == "hello"

    def test_extract_output_chat_completions(self):
        response = MagicMock()
        response.output_parsed = None
        response.output_text = None
        response.choices = [MagicMock(message=MagicMock(content="legacy"))]
        assert _extract_output(response) == "legacy"

    def test_extract_output_ollama_dict(self):
        assert _extract_output({"message": {"content": "hi"}}) == "hi"

    def test_extract_usage_responses_api(self):
        usage = MagicMock(input_tokens=10, output_tokens=5, total_tokens=None)
        response = MagicMock(usage=usage)
        assert _extract_usage(response) == {"input": 10, "output": 5, "total": 15}

    def test_extract_usage_missing(self):
        response = MagicMock(usage=None)
        assert _extract_usage(response) is None
