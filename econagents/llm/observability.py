"""Observability interfaces for LLM providers."""

import importlib.util
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ObservabilityProvider(ABC):
    """Base class for observability providers."""

    @abstractmethod
    def track_llm_call(
        self,
        name: str,
        model: str,
        messages: List[Dict[str, Any]],
        response: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Track an LLM call directly without creating a run tree.

        Args:
            name: Name of the operation.
            model: Model used for the call.
            messages: Messages sent to the model.
            response: Response from the model.
            metadata: Additional metadata for the call.
        """
        ...


class NoOpObservability(ObservabilityProvider):
    """No-op observability provider that does nothing."""

    def track_llm_call(
        self,
        name: str,
        model: str,
        messages: List[Dict[str, Any]],
        response: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """No-op implementation of track_llm_call."""
        pass


class LangSmithObservability(ObservabilityProvider):
    """LangSmith observability provider."""

    def __init__(self) -> None:
        """Initialize the LangSmith observability provider."""
        self._check_langsmith_available()

    def _check_langsmith_available(self) -> None:
        """Check if LangSmith is available."""
        if not importlib.util.find_spec("langsmith"):
            raise ImportError("LangSmith is not installed. Install it with: pip install econagents[langsmith]")

    def _create_run_tree(
        self,
        name: str,
        run_type: str,
        inputs: Dict[str, Any],
    ) -> Any:
        """Create a LangSmith run tree.

        Args:
            name: Name of the run.
            run_type: Type of the run (e.g., "chain", "llm").
            inputs: Inputs for the run.

        Returns:
            A LangSmith RunTree object.
        """
        try:
            from langsmith.run_trees import RunTree

            run_tree = RunTree(name=name, run_type=run_type, inputs=inputs)
            run_tree.post()
            return run_tree
        except ImportError:
            logger.warning("LangSmith is not available. Using no-op run tree.")
            return {"name": name, "run_type": run_type, "inputs": inputs}

    def _create_child_run(
        self,
        parent_run: Any,
        name: str,
        run_type: str,
        inputs: Dict[str, Any],
    ) -> Any:
        """Create a child run in LangSmith.

        Args:
            parent_run: Parent RunTree object.
            name: Name of the child run.
            run_type: Type of the child run.
            inputs: Inputs for the child run.

        Returns:
            A child RunTree object.
        """
        try:
            child_run = parent_run.create_child(
                name=name,
                run_type=run_type,
                inputs=inputs,
            )
            child_run.post()
            return child_run
        except (ImportError, AttributeError):
            logger.warning("LangSmith create_child failed. Using no-op child run.")
            return {"name": name, "run_type": run_type, "inputs": inputs, "parent": parent_run}

    def _end_run(
        self,
        run: Any,
        outputs: Dict[str, Any],
    ) -> None:
        """End a LangSmith run with outputs.

        Args:
            run: RunTree object to end.
            outputs: Outputs of the run.
        """
        try:
            run.end(outputs=outputs)
            run.patch()
        except (ImportError, AttributeError) as e:
            logger.warning(f"LangSmith end_run failed: {e}")

    def track_llm_call(
        self,
        name: str,
        model: str,
        messages: List[Dict[str, Any]],
        response: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Track an LLM call using LangSmith RunTree.

        Args:
            name: Name of the operation.
            model: Model used for the call.
            messages: Messages sent to the model.
            response: Response from the model.
            metadata: Additional metadata for the call.
        """
        try:
            # Create a top-level run
            run_tree = self._create_run_tree(
                name=name, run_type="chain", inputs={"messages": messages, "metadata": metadata or {}}
            )

            # Create LLM child run
            child_run = self._create_child_run(
                parent_run=run_tree, name=f"{model} Call", run_type="llm", inputs={"messages": messages}
            )

            # End the runs
            self._end_run(child_run, outputs=response)

            # Get the content from the response if it's in the expected format
            output_content = None
            if hasattr(response, "choices") and response.choices:
                if hasattr(response.choices[0], "message") and hasattr(response.choices[0].message, "content"):
                    output_content = response.choices[0].message.content

            self._end_run(run_tree, outputs={"response": output_content or response})
        except Exception as e:
            logger.warning(f"Failed to track LLM call with LangSmith: {e}")


class LangFuseObservability(ObservabilityProvider):
    """LangFuse observability provider."""

    def __init__(self) -> None:
        """Initialize the LangFuse observability provider."""
        self._check_langfuse_available()
        self._langfuse_client = None

    def _check_langfuse_available(self) -> None:
        """Check if LangFuse is available."""
        if not importlib.util.find_spec("langfuse"):
            raise ImportError("LangFuse is not installed. Install it with: pip install econagents[langfuse]")

    def _get_langfuse_client(self) -> Any:
        """Get or create a LangFuse client."""
        if self._langfuse_client is None:
            try:
                from langfuse import Langfuse

                self._langfuse_client = Langfuse()
            except ImportError:
                logger.warning("LangFuse is not available.")
                return None
        return self._langfuse_client

    def track_llm_call(
        self,
        name: str,
        model: str,
        messages: List[Dict[str, Any]],
        response: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Track an LLM call using LangFuse generation.

        Args:
            name: Name of the operation.
            model: Model used for the call.
            messages: Messages sent to the model.
            response: Response from the model.
            metadata: Additional metadata for the call.
        """
        client = self._get_langfuse_client()
        if client is None:
            return

        try:
            # Create a generation in Langfuse
            trace = client.trace(name=name, metadata={"model": model, **metadata} if metadata else {}, input=messages)
            generation = trace.generation(
                name=name + "_generation",
                model=model,
                model_parameters=metadata.get("model_parameters", {}) if metadata else {},
                input=messages,
                metadata=metadata or {},
            )

            # Get response content in appropriate format
            output_content = response
            if hasattr(response, "choices") and response.choices:
                if hasattr(response.choices[0], "message") and hasattr(response.choices[0].message, "content"):
                    output_content = response.choices[0].message.content
            elif isinstance(response, dict) and "message" in response and "content" in response["message"]:
                output_content = response["message"]["content"]

            # Update generation and set end time
            generation.end(output=output_content)
            trace.update(output=output_content)

            # Flush to ensure all requests are sent
            client.flush()
        except Exception as e:
            logger.warning(f"Failed to track LLM call with LangFuse: {e}")


def get_observability_provider(provider_name: str = "noop") -> ObservabilityProvider:
    """Get an observability provider by name.

    Args:
        provider_name: The name of the provider to get.
                      Options: "noop", "langsmith", "langfuse"

    Returns:
        An observability provider.

    Raises:
        ValueError: If the provider_name is invalid.
    """
    if provider_name == "noop":
        return NoOpObservability()
    elif provider_name == "langsmith":
        try:
            return LangSmithObservability()
        except ImportError as e:
            logger.warning(f"Failed to initialize LangSmith: {e}")
            logger.warning("Falling back to NoOpObservability")
            return NoOpObservability()
    elif provider_name == "langfuse":
        try:
            return LangFuseObservability()
        except ImportError as e:
            logger.warning(f"Failed to initialize LangFuse: {e}")
            logger.warning("Falling back to NoOpObservability")
            return NoOpObservability()
    else:
        raise ValueError(f"Invalid observability provider: {provider_name}")
