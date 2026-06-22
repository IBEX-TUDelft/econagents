from pydantic import Field

from econagents.runtime import create_game_state
from econagents.domain.state.game import GameState, MetaInformation


class CustomMeta(MetaInformation):
    label: str = "test"


class CustomState(GameState):
    meta: CustomMeta = Field(default_factory=CustomMeta)


def test_create_game_state_sets_meta_game_id():
    state = create_game_state(CustomState, game_id=99)

    assert isinstance(state, CustomState)
    assert state.meta.game_id == 99
    assert state.meta.label == "test"
