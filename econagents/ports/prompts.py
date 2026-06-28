"""Prompt rendering ports."""

from pathlib import Path
from typing import Any, Callable, Literal, Protocol

from econagents.domain.messages import PhaseId

PromptType = Literal["system", "user"]
PromptResolver = Callable[[PromptType, PhaseId, str, Path], Path | None]


class PromptRendererPort(Protocol):
    """Render phase prompts from state/context without owning agent policy."""

    def render(
        self,
        context: dict[str, Any],
        prompt_type: PromptType,
        phase: PhaseId,
        prompts_path: Path,
        role_names: list[str],
        resolver: PromptResolver | None = None,
        logger: Any | None = None,
    ) -> str:
        """Render a prompt from the configured prompt source."""
        ...
