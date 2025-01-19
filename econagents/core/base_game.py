from typing import Any

from econagents.core.phases import Phase


class BaseGame:
    """
    A base class representing an economic game with phases, roles, etc. Subclass or instantiate with a spec to capture domain-specific logic.
    """

    def __init__(self, game_spec: dict[str, Any]) -> None:
        """Initialize a new game instance."""
        self.game_spec = game_spec
        self.phases = self._parse_phases()

    def _parse_phases(self) -> list[Phase]:
        """Convert phase strings from spec into Phase enums."""
        phase_list = self.game_spec.get("phases", [])
        return [Phase[p.upper()] for p in phase_list]

    @property
    def name(self) -> str:
        """Get the game name."""
        return self.game_spec.get("name", "UnnamedGame")

    def get_roles(self) -> list[str]:
        """Get the list of roles defined for this game."""
        return self.game_spec.get("roles", [])
