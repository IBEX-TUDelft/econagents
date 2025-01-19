from enum import Enum, auto


class Phase(Enum):
    """
    Standard game phases.
    """

    INSTRUCTIONS = auto()
    REQUEST = auto()
    OFFER = auto()
    DELIBERATION = auto()
    VOTING = auto()
    RESULTS = auto()
    FINISHED = auto()
