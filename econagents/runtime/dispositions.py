"""Disposition hooks: wait for the server's answer to a submission before the next decision."""

import hashlib
import json
from typing import Any, Callable, Iterable, Literal, Protocol

from econagents.domain.messages import Event
from econagents.domain.state.game import GameState

UnknownPolicy = Literal["block", "continue"]
DecisionInputMode = Literal["frozen", "guard-discard", "guard-rerun"]
DecisionTrace = Callable[[dict[str, Any]], Any]
InputRevision = Callable[[GameState], str]

UNKNOWN = "unknown"


class DispositionTracker(Protocol):
    """Maps server events to the dispositions of an agent's own submissions.

    ``submitted`` is called with a fresh decision id just before the action's frame is handed to the
    transport; returning ``True`` means the agent must hear a disposition for it before its next
    decision. ``observe`` sees every event, in arrival order, after it was projected into the state,
    and returns the ``(decision_id, disposition)`` pairs it resolves. A disposition that starts with
    ``"unknown"`` means the outcome could not be established (see ``Agent(on_unknown=...)``). Once the
    tracker has evidence for such a submission, ``observe`` reports its decision id again with the
    reconciled disposition; that report, not any particular event, is what releases a block.

    A tracker may also define ``not_transmitted(decision_id)``; the agent calls it when the transport
    raised while sending a submission it had announced with ``submitted``.
    """

    def submitted(self, decision_id: str, message: dict[str, Any], state: GameState) -> bool:
        """Record an own submission; return whether the agent must wait for its disposition."""
        ...

    def observe(self, event: Event, state: GameState) -> Iterable[tuple[str, str]]:
        """Return the dispositions this event settles, as ``(decision_id, disposition)`` pairs."""
        ...


def is_unknown(disposition: str) -> bool:
    """Whether a disposition says the outcome of the submission is unknown."""
    return disposition.startswith(UNKNOWN)


def state_revision(state: GameState) -> str:
    """sha256 of the state's canonical JSON form; the default decision-input revision."""
    dumped = state.model_dump(mode="json")
    return hashlib.sha256(json.dumps(dumped, sort_keys=True, default=str).encode()).hexdigest()
