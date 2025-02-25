import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

from econagents.core.state.game import PropertyMapping

load_dotenv()

PATH_GAME = Path(__file__).parent
PATH_PROMPTS = PATH_GAME / "prompts"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
property_mappings = [
    # Game state mappings
    PropertyMapping(event_key="phase", state_key="phase", state_type="meta"),
    PropertyMapping(event_key="name", state_key="player_name", state_type="meta"),
    PropertyMapping(event_key="number", state_key="player_number", state_type="meta"),
    PropertyMapping(event_key="players", state_key="players", state_type="meta"),
    # Private information mappings
    PropertyMapping(event_key="wallet", state_key="wallet", state_type="private"),
    PropertyMapping(event_key="property", state_key="property", state_type="private"),
    PropertyMapping(event_key="declarations", state_key="declarations", state_type="private"),
    PropertyMapping(event_key="signals", state_key="value_signals", state_type="private"),
    # Public information mappings
    PropertyMapping(event_key="conditions", state_key="conditions", state_type="public"),
    PropertyMapping(event_key="winningCondition", state_key="winning_condition", state_type="public"),
    PropertyMapping(event_key="boundaries", state_key="boundaries", state_type="public"),
    PropertyMapping(event_key="taxRate", state_key="tax_rate", state_type="public"),
    PropertyMapping(event_key="initialTaxRate", state_key="initial_tax_rate", state_type="public"),
    PropertyMapping(event_key="finalTaxRate", state_key="final_tax_rate", state_type="public"),
    PropertyMapping(event_key="publicSignal", state_key="public_signal", state_type="public"),
    PropertyMapping(event_key="condition", state_key="winning_condition", state_type="public"),
]


class GameMappings(BaseModel):
    roles: dict[int, str]
    phases: dict[int, str]
    conditions: dict[int, str]


game_mappings = GameMappings(
    roles={
        1: "Speculator",
        2: "Developer",
        3: "Owner",
    },
    phases={
        0: "Introduction",
        1: "Presentation",
        2: "Declaration",
        3: "Speculation",
        4: "Reconciliation",
        5: "Transition",
        6: "Market",
        7: "Declaration",
        8: "Speculation",
        9: "Results",
    },
    conditions={0: "noProject", 1: "projectA"},
)
