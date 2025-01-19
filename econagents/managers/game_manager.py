from typing import Any, Optional

from econagents.core.base_game import BaseGame
from econagents.core.phases import Phase


class GameManager:
    """
    Manages the lifecycle (phases) of a specific game instance, using a BaseGame (or subclass).
    """

    def __init__(self, game_spec: dict[str, Any], monitoring: Optional[Any] = None) -> None:
        """Initialize a new game manager."""
        self.game_spec = game_spec
        self.game = BaseGame(game_spec)
        self.current_phase_index = 0
        self.monitoring = monitoring
        self.history: list[dict[str, Any]] = []

    def start_game(self) -> None:
        """Initialize the game at the first phase."""
        if self.game.phases:
            self.current_phase_index = 0
            if self.monitoring:
                self.monitoring.on_game_setup(self.game_spec)
        else:
            raise ValueError("Game has no phases defined")

    def next_phase(self) -> None:
        """Advance to the next phase, if any."""
        if self.current_phase_index < len(self.game.phases) - 1:
            self.current_phase_index += 1
            current_state = self.get_state()
            self.history.append(current_state)
            if self.monitoring:
                self.monitoring.on_phase_end(self.current_phase_index, current_state)

    def get_current_phase(self) -> Optional[Phase]:
        """Return the current phase object or enum from the game."""
        if self.game.phases:
            return self.game.phases[self.current_phase_index]
        return None

    def is_finished(self) -> bool:
        """Check if the game has reached the last phase."""
        return self.current_phase_index >= len(self.game.phases) - 1

    def get_state(self) -> dict[str, Any]:
        """Return a dictionary describing the current game state."""
        return {
            "phase": self.get_current_phase(),
            "phase_index": self.current_phase_index,
            "game_name": self.game.name,
            "roles": self.game.get_roles(),
        }

    def finalize_game(self) -> dict[str, Any]:
        """Finalize the game and return results."""
        final_state = self.get_state()
        self.history.append(final_state)

        if self.monitoring:
            self.monitoring.on_game_end()

        return {"final_state": final_state, "history": self.history, "config": self.game_spec}
