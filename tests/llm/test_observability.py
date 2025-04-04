import importlib.util
import logging
import pytest
from unittest.mock import MagicMock, patch

from econagents.llm.observability import (
    NoOpObservability,
    LangSmithObservability,
    LangFuseObservability,
    ObservabilityProvider,
    get_observability_provider,
)


class TestObservabilityProviders:
    """Tests for the observability providers."""

    def test_noop_observability(self):
        """Test that the NoOpObservability provider initializes and does nothing."""
        provider = NoOpObservability()
        # Should not raise any exceptions
        provider.track_llm_call(name="test", model="test-model", messages=[], response={}, metadata={})

    @patch("importlib.util.find_spec")
    def test_langsmith_observability_initialization(self, mock_find_spec):
        """Test that LangSmithObservability initializes correctly."""
        # Test when LangSmith is available
        mock_find_spec.return_value = True
        provider = LangSmithObservability()
        assert isinstance(provider, ObservabilityProvider)

        # Test when LangSmith is not available
        mock_find_spec.return_value = None
        with pytest.raises(ImportError) as exc_info:
            LangSmithObservability()
        assert "LangSmith is not installed" in str(exc_info.value)

    @patch("importlib.util.find_spec")
    def test_langfuse_observability_initialization(self, mock_find_spec):
        """Test that LangFuseObservability initializes correctly."""
        # Test when LangFuse is available
        mock_find_spec.return_value = True
        provider = LangFuseObservability()
        assert isinstance(provider, ObservabilityProvider)

        # Test when LangFuse is not available
        mock_find_spec.return_value = None
        with pytest.raises(ImportError) as exc_info:
            LangFuseObservability()
        assert "LangFuse is not installed" in str(exc_info.value)

    def test_langsmith_track_llm_call(self):
        """Test tracking an LLM call with LangSmithObservability."""
        with patch("importlib.util.find_spec", return_value=True):
            provider = LangSmithObservability()

            # Mock the methods that interact with LangSmith
            provider._create_run_tree = MagicMock(return_value=MagicMock())
            provider._create_child_run = MagicMock(return_value=MagicMock())
            provider._end_run = MagicMock()

            # Call track_llm_call
            provider.track_llm_call(
                name="test_call",
                model="test-model",
                messages=[{"role": "user", "content": "Hello"}],
                response=MagicMock(),
                metadata={"test": "metadata"},
            )

            # Assert methods were called
            provider._create_run_tree.assert_called_once()
            provider._create_child_run.assert_called_once()
            assert provider._end_run.call_count == 2

    @patch("langfuse.Langfuse")
    def test_langfuse_track_llm_call(self, mock_langfuse_class):
        """Test tracking an LLM call with LangFuseObservability."""
        mock_langfuse = MagicMock()
        mock_trace = MagicMock()
        mock_generation = MagicMock()

        mock_langfuse.trace.return_value = mock_trace
        mock_trace.generation.return_value = mock_generation

        mock_langfuse_class.return_value = mock_langfuse

        with patch("importlib.util.find_spec", return_value=True):
            provider = LangFuseObservability()
            provider._langfuse_client = mock_langfuse

            # Call track_llm_call
            provider.track_llm_call(
                name="test_call",
                model="test-model",
                messages=[{"role": "user", "content": "Hello"}],
                response={"message": {"content": "test response"}},
                metadata={"test": "metadata"},
            )

            # Assert methods were called
            mock_langfuse.trace.assert_called_once()
            mock_trace.generation.assert_called_once()
            mock_generation.end.assert_called_once()
            mock_trace.update.assert_called_once()
            mock_langfuse.flush.assert_called_once()

    def test_get_observability_provider_noop(self):
        """Test getting the NoOpObservability provider."""
        provider = get_observability_provider("noop")
        assert isinstance(provider, NoOpObservability)

    @patch("econagents.llm.observability.LangSmithObservability")
    def test_get_observability_provider_langsmith(self, mock_langsmith):
        """Test getting the LangSmithObservability provider."""
        # Test successful initialization
        provider = get_observability_provider("langsmith")
        mock_langsmith.assert_called_once()

        # Test fallback to NoOpObservability on ImportError
        mock_langsmith.side_effect = ImportError("Test error")
        provider = get_observability_provider("langsmith")
        assert isinstance(provider, NoOpObservability)

    @patch("econagents.llm.observability.LangFuseObservability")
    def test_get_observability_provider_langfuse(self, mock_langfuse):
        """Test getting the LangFuseObservability provider."""
        # Test successful initialization
        provider = get_observability_provider("langfuse")
        mock_langfuse.assert_called_once()

        # Test fallback to NoOpObservability on ImportError
        mock_langfuse.side_effect = ImportError("Test error")
        provider = get_observability_provider("langfuse")
        assert isinstance(provider, NoOpObservability)

    def test_get_observability_provider_invalid(self):
        """Test getting an invalid observability provider."""
        with pytest.raises(ValueError) as exc_info:
            get_observability_provider("invalid")
        assert "Invalid observability provider" in str(exc_info.value)

    def test_langsmith_create_run_tree(self):
        """Test creating a run tree with LangSmithObservability."""
        with patch("importlib.util.find_spec", return_value=True):
            provider = LangSmithObservability()

            # Test when langsmith is available
            mock_run_tree = MagicMock()
            with patch("langsmith.run_trees.RunTree", return_value=mock_run_tree):
                result = provider._create_run_tree("test_run", "test_type", {"test": "input"})
                assert result == mock_run_tree
                mock_run_tree.post.assert_called_once()

            # Test when langsmith is not available
            with patch("langsmith.run_trees.RunTree", side_effect=ImportError):
                result = provider._create_run_tree("test_run", "test_type", {"test": "input"})
                assert isinstance(result, dict)
                assert result["name"] == "test_run"
                assert result["run_type"] == "test_type"
                assert result["inputs"] == {"test": "input"}

    def test_langfuse_get_langfuse_client(self):
        """Test getting the LangFuse client."""
        with patch("importlib.util.find_spec", return_value=True):
            provider = LangFuseObservability()

            # Test when langfuse is available
            mock_langfuse = MagicMock()
            with patch("langfuse.Langfuse", return_value=mock_langfuse):
                result = provider._get_langfuse_client()
                assert result == mock_langfuse
                assert provider._langfuse_client == mock_langfuse

            # Test when langfuse is not available
            provider._langfuse_client = None
            with patch("langfuse.Langfuse", side_effect=ImportError):
                result = provider._get_langfuse_client()
                assert result is None
