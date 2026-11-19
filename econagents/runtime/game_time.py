"""The game's own time as an agent sees it: it stands still while the game is paused."""

import math
import time
from collections import deque
from typing import Any, Callable, Optional

GAMETIME_SAMPLES = 10


def _milliseconds() -> float:
    return time.monotonic() * 1000


def _is_time(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class GameTime:
    """Estimate an ibex game's time from the messages an agent receives.

    An ibex server counts a game's time in milliseconds from the game's start and sends it with every
    message (``meta.gametime``). It sends no wall-clock time, and a phase timer's end is a game time. Each
    message gives a pair: its game time and the local clock when it arrived. The estimate takes the
    smallest difference among the last ``samples`` pairs, which is the least delayed message.

    While the game is paused (ibex 0.9.0) its time stands still, so ``now`` returns the game time of the
    pause and ``remaining`` stops counting down. ``resume`` forgets the earlier pairs, which the pause
    shifted. ``local_now`` is the local clock in milliseconds (the monotonic clock by default).
    """

    def __init__(self, local_now: Callable[[], float] = _milliseconds, samples: int = GAMETIME_SAMPLES) -> None:
        self._local_now = local_now
        self._offsets: deque[float] = deque(maxlen=samples)
        self._paused = False
        self._frozen_at: Optional[float] = None

    @property
    def paused(self) -> bool:
        """Whether the game's time stands still."""
        return self._paused

    @property
    def offset(self) -> Optional[float]:
        """The local clock at game time 0, or ``None`` before any message carried a game time."""
        return min(self._offsets) if self._offsets else None

    def observe(self, gametime: Any, received_at: Optional[float] = None) -> None:
        """Note a message's game time as it arrives; ignored while paused, or when it is not a time."""
        if self._paused or not _is_time(gametime):
            return
        self._offsets.append((self._local_now() if received_at is None else received_at) - gametime)

    def now(self) -> Optional[float]:
        """The game time now, or ``None`` when no message has carried one."""
        if self._paused:
            return self._frozen_at
        offset = self.offset
        return None if offset is None else self._local_now() - offset

    def local_time_of(self, gametime: float) -> Optional[float]:
        """When a game time falls on the local clock if the game keeps running, or ``None`` when unknown."""
        now = self.now()
        return None if now is None else self._local_now() + gametime - now

    def remaining(self, gametime: float) -> Optional[float]:
        """Milliseconds left until a game time, never negative, or ``None`` when unknown."""
        now = self.now()
        return None if now is None else max(0.0, gametime - now)

    def pause(self, gametime: Any = None) -> None:
        """The game paused at ``gametime`` (the current estimate when it is not given)."""
        if self._paused:
            return
        self._frozen_at = float(gametime) if _is_time(gametime) else self.now()
        self._paused = True

    def resume(self, gametime: Any = None, received_at: Optional[float] = None) -> None:
        """The game resumed at ``gametime`` (the game time of the pause when it is not given)."""
        if not self._paused:
            return
        at = float(gametime) if _is_time(gametime) else self._frozen_at
        self._paused = False
        self._frozen_at = None
        self._offsets.clear()
        self.observe(at, received_at)
