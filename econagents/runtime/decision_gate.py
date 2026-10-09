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
    """

    def is_decided(self, occurrence: PhaseOccurrence) -> bool:
        """Return whether the decision for ``occurrence`` already completed."""
        ...

    def mark_decided(self, occurrence: PhaseOccurrence, outcome: DecisionOutcome) -> None:
        """Record that the decision for ``occurrence`` completed: its action was sent, or it decided to hold."""
        ...
