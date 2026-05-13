"""Persona storage and retrieval.

A ``Persona`` is a stable identity (demographics, traits, optional bio) stored
as a YAML file. Personas are loaded by ``id`` from a user-provided directory,
falling back to a bundled starter library.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field

BUILTIN_LIBRARY = Path(__file__).parent / "library"


class PersonaNotFoundError(LookupError):
    """Raised when a persona id cannot be resolved in any configured location."""

    def __init__(self, persona_id: str, searched: list[Path]):
        self.persona_id = persona_id
        self.searched = searched
        locations = ", ".join(str(p) for p in searched) if searched else "<none>"
        super().__init__(f"Persona '{persona_id}' not found in: {locations}")


class Persona(BaseModel):
    """Stable, portable identity injected into agent prompts."""

    id: str
    demographics: dict[str, Any] = Field(default_factory=dict)
    traits: dict[str, Any] = Field(default_factory=dict)
    bio: str = ""

    model_config = ConfigDict(frozen=True, extra="forbid")


def load_persona(persona_id: str, user_dir: Optional[Path] = None) -> Persona:
    """Resolve ``persona_id`` by checking ``user_dir`` first, then the bundled library.

    Each root is searched recursively for ``<persona_id>.yaml``, so subdirectories
    (e.g. ``library/archetypes/``) work without the caller knowing about them.
    Ids must be unique within a tree; if two files share a stem, lookup is
    deterministic on path-sorted order but a duplicate id is a configuration bug.

    Raises ``PersonaNotFoundError`` if not found in either location.
    """
    searched: list[Path] = []
    for root in (user_dir, BUILTIN_LIBRARY):
        if root is None or not root.is_dir():
            continue
        searched.append(root)
        matches = sorted(root.rglob(f"{persona_id}.yaml"))
        if matches:
            return Persona.model_validate(yaml.safe_load(matches[0].read_text()))
    raise PersonaNotFoundError(persona_id, searched)


def save_persona(persona: Persona, path: Path) -> None:
    """Write ``persona`` to ``path`` as YAML (sorted keys, unicode preserved)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(persona.model_dump(), sort_keys=True, allow_unicode=True))


__all__ = [
    "BUILTIN_LIBRARY",
    "Persona",
    "PersonaNotFoundError",
    "load_persona",
    "save_persona",
]
