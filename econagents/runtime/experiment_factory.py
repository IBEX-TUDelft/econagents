"""Experiment assembly helpers."""

from typing import Type, TypeVar

from econagents.domain.state.game import GameState

StateT = TypeVar("StateT", bound=GameState)


def create_game_state(state_type: Type[StateT], game_id: int, **kwargs) -> StateT:
    """Create a game state instance for a game."""
    state = state_type(**kwargs)
    state.meta.game_id = game_id
    return state
