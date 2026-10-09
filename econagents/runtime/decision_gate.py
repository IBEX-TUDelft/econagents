"""Decision gate hook for non-continuous phase occurrences."""

from typing import Any, Literal, NamedTuple, Protocol

from econagents.domain.messages import PhaseId

DecisionOutcome = Literal["sent", "hold"]


class PhaseOccurrence(NamedTuple):
    """One occurrence of a phase: the phase id and ``state.meta.round`` (``None`` when the state has no round)."""

    phase: PhaseId | None
    round: Any


class DecisionGate(Protocol):
    """Durable record of which non-continuous phase occurrences an agent has already decided.

    ``Agent`` always remembers, in memory, that it completed the decision for its current occurrence.
    A gate passed as ``Agent(decision_gate=...)`` is consulted in addition, so a store that outlives the
    process (for example a response journal) can stop a restarted agent from deciding again.

    The in-memory record resets whenever the agent moves to another occurrence, but a store keyed on
    ``(phase, round)`` also answers ``True`` when a game returns to the same phase id within one round,
    so such a game needs a key that tells those visits apart. If ``is_decided`` raises, the agent logs
    the error and makes no decision on that transition; if ``mark_decided`` raises, the error is logged.
    """

    def is_decided(self, occurrence: PhaseOccurrence) -> bool:
        """Return whether the decision for ``occurrence`` already completed."""
        ...

    def mark_decided(self, occurrence: PhaseOccurrence, outcome: DecisionOutcome) -> None:
        """Record that the decision for ``occurrence`` completed: its action was sent, or it decided to hold."""
        ...
