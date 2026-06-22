"""Jinja prompt renderer adapter."""

from pathlib import Path
from typing import Any

from jinja2 import FileSystemLoader
from jinja2.sandbox import SandboxedEnvironment

from econagents.domain.messages import PhaseId
from econagents.ports.prompts import PromptResolver, PromptType


class JinjaPromptRenderer:
    """Render role/phase prompt templates from a directory."""

    def resolve_prompt_file(
        self,
        prompt_type: PromptType,
        phase: PhaseId,
        role: str,
        prompts_path: Path,
    ) -> Path | None:
        """Resolve the most specific prompt file for one role."""
        phase_file = prompts_path / f"{role.lower()}_{prompt_type}_phase_{phase}.jinja2"
        if phase_file.exists():
            return phase_file

        general_file = prompts_path / f"{role.lower()}_{prompt_type}.jinja2"
        if general_file.exists():
            return general_file

        return None

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
        """Render a prompt using role-specific and all-role fallbacks."""
        env = SandboxedEnvironment(loader=FileSystemLoader(prompts_path))
        resolve = resolver or self.resolve_prompt_file

        for role in role_names:
            prompt_file_path = resolve(prompt_type, phase, role, prompts_path)
            if prompt_file_path is None:
                continue

            template_filename = str(prompt_file_path.relative_to(prompts_path))
            try:
                template = env.get_template(template_filename)
                return template.render(**context)
            except Exception as exc:
                if logger is not None:
                    logger.error(f"Error loading/rendering template {template_filename}: {exc}")
                raise

        raise FileNotFoundError(
            f"No prompt template found for type={prompt_type}, phase={phase}, roles={role_names} in {prompts_path}"
        )
