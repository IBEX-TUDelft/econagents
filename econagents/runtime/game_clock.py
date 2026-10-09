"""Pausable clock behind the ``GameRunner`` timeout watchdog."""

import asyncio
import logging
from typing import Any, Collection, Literal, Optional

from econagents.domain.messages import PhaseId

TimeoutReason = Literal["gameplay", "pre_game"]


class GameClock:
    """Split a run's time into pre-game waiting and gameplay.

    Agents report phases as ``(round, phase)`` occurrences. The first report of an occurrence moves the
    game into it; later reports of the same occurrence (the replay after a join or reconnect, or the same
    phase seen by another agent) change nothing. Gameplay time accumulates only while the game is in a
    phase outside ``pre_game_phases``, so a later round's pre-game phase pauses the gameplay clock
    instead of restarting it. Pre-game time accumulates before the first report and while the game is in
    a pre-game phase.

    Until the first report, the gameplay budget also counts from the start of the run, so agents that
    never report a phase keep the from-start timeout. The first report discards that provisional time.
    """

    def __init__(
        self,
        *,
        max_game_duration: Optional[float],
        max_pre_game_duration: Optional[float],
        pre_game_phases: Collection[PhaseId],
        logger: logging.Logger,
    ) -> None:
        self.gameplay_budget = max_game_duration if max_game_duration and max_game_duration > 0 else None
        self.pre_game_budget = max_pre_game_duration if max_pre_game_duration and max_pre_game_duration > 0 else None
        self.pre_game_phases = frozenset(pre_game_phases)
        self.logger = logger
        self.phase: Optional[PhaseId] = None
        self.round: Any = None
        self.gameplay_start_phase: Optional[PhaseId] = None
        self._loop = asyncio.get_running_loop()
        self._since = self._loop.time()
        self._gameplay = 0.0
        self._pre_game = 0.0
        self._seen: set[tuple[Any, PhaseId]] = set()
        self._changed = asyncio.Event()

    @property
    def enabled(self) -> bool:
        """Whether any budget is set."""
        return self.gameplay_budget is not None or self.pre_game_budget is not None

    @property
    def in_gameplay(self) -> bool:
        """Whether the game is in a reported phase outside ``pre_game_phases``."""
        return self.phase is not None and self.phase not in self.pre_game_phases

    def observe(self, round_: Any, phase: Optional[PhaseId]) -> None:
        """Record a phase reported by an agent."""
        if phase is None or (round_, phase) in self._seen:
            return
        self._seen.add((round_, phase))
        was_reported = self.phase is not None
        was_gameplay = self.in_gameplay
        self._accumulate()
        if not was_reported:
            self._gameplay = 0.0
        self.phase, self.round = phase, round_

        if self.in_gameplay and self.gameplay_start_phase is None:
            self.gameplay_start_phase = phase
            self.logger.info(f"Gameplay started (phase={phase}, round={round_}); gameplay budget {self._budget_text()}")
        elif self.in_gameplay and not was_gameplay:
            self.logger.info(
                f"Gameplay clock resumed (phase={phase}, round={round_}) at {self._gameplay:.1f}s of "
                f"{self._budget_text()}"
            )
        elif was_gameplay and not self.in_gameplay:
            self.logger.info(
                f"Gameplay clock paused (phase={phase}, round={round_}) at {self._gameplay:.1f}s of "
                f"{self._budget_text()}"
            )
        self._changed.set()

    async def wait_for_timeout(self) -> TimeoutReason:
        """Return once a budget is used up, naming which one."""
        while True:
            self._changed.clear()
            remaining, reason = self._next_timeout()
            if reason is not None and remaining is not None and remaining <= 0:
                return reason
            try:
                await asyncio.wait_for(self._changed.wait(), remaining)
            except asyncio.TimeoutError:
                pass

    def _accumulate(self) -> None:
        now = self._loop.time()
        elapsed = now - self._since
        if self.in_gameplay:
            self._gameplay += elapsed
        else:
            self._pre_game += elapsed
            if self.phase is None:
                self._gameplay += elapsed
        self._since = now

    def _next_timeout(self) -> tuple[Optional[float], Optional[TimeoutReason]]:
        elapsed = self._loop.time() - self._since
        candidates: list[tuple[float, TimeoutReason]] = []
        if self.gameplay_budget is not None and (self.in_gameplay or self.phase is None):
            candidates.append((self.gameplay_budget - self._gameplay - elapsed, "gameplay"))
        if self.pre_game_budget is not None and not self.in_gameplay:
            candidates.append((self.pre_game_budget - self._pre_game - elapsed, "pre_game"))
        if not candidates:
            return None, None
        return min(candidates)

    def _budget_text(self) -> str:
        return "unlimited" if self.gameplay_budget is None else f"{self.gameplay_budget}s"
