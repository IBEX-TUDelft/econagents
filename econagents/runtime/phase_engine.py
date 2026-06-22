"""Phase execution policy."""

import random
from collections.abc import Callable

from econagents.domain.messages import PhaseId


class PhaseEngine:
    """Decide whether phases are continuous and when repeated actions occur."""

    def __init__(
        self,
        continuous_phases: set[PhaseId] | None = None,
        min_action_delay: int | None = None,
        max_action_delay: int | None = None,
        random_int: Callable[[int, int], int] | None = None,
    ) -> None:
        self.continuous_phases = continuous_phases or set()
        self.min_action_delay = min_action_delay
        self.max_action_delay = max_action_delay
        self._random_int = random_int

    def is_continuous(self, phase: PhaseId) -> bool:
        """Return whether a phase should run repeated actions."""
        return phase in self.continuous_phases

    def next_action_delay(self) -> int:
        """Return the delay before the next action in a continuous phase."""
        if self.min_action_delay is None or self.max_action_delay is None:
            raise ValueError("Continuous phase delays must be configured")
        random_int = self._random_int or random.randint
        return random_int(self.min_action_delay, self.max_action_delay)
