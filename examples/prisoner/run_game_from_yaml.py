import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

from econagents.adapters.config import run_experiment_from_yaml
from examples.prisoner.server.create_game import create_game_from_specs


DEFAULT_CONFIG = Path(__file__).parent / "prisoner.yaml"


async def main(config_path: Path = DEFAULT_CONFIG):
    """Run the experiment described by ``config_path``.

    Run from the repository root:

        python -m examples.prisoner.run_game_from_yaml                            # OpenAI, needs OPENAI_API_KEY
        python -m examples.prisoner.run_game_from_yaml prisoner_openrouter.yaml   # OpenRouter, needs OPENROUTER_API_KEY
    """
    load_dotenv()
    game_specs = create_game_from_specs()
    login_payloads = [
        {"agent_id": i, "type": "join", "gameId": game_specs["game_id"], "recovery": code}
        for i, code in enumerate(game_specs["recovery_codes"], start=1)
    ]

    await run_experiment_from_yaml(config_path, login_payloads, game_id=game_specs["game_id"])


if __name__ == "__main__":
    config = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CONFIG
    if not config.is_absolute() and not config.exists():
        config = Path(__file__).parent / config
    asyncio.run(main(config))
