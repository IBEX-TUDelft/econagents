import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PATH_GAME = Path(__file__).parent
PATH_PROMPTS = PATH_GAME / "prompts"
