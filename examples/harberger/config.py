import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()

PATH_GAME = Path(__file__).parent
PATH_PROMPTS = PATH_GAME / "prompts"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


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
