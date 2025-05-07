import asyncio
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from econagents.config_parser.ibex_tudelft import run_experiment_from_yaml
from examples.ibex_tudelft.create_game import create_game_from_specs

load_dotenv()

HOSTNAME = os.getenv("HOSTNAME")
PORT = os.getenv("PORT")
USERNAME = os.getenv("GAME_USERNAME")
PASSWORD = os.getenv("GAME_PASSWORD")


async def main():
    """Main function to run the game."""
    new_game_data = create_game_from_specs(
        specs_path=Path(__file__).parent / "futarchy.json",
        base_url=f"http://{HOSTNAME}",
        game_name=f"futarchy {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        credentials={"username": USERNAME, "password": PASSWORD},
    )
    game_id = new_game_data["game_id"]
    login_payloads = new_game_data["login_payloads"]

    await run_experiment_from_yaml(Path(__file__).parent / "futarchy_config.yaml", login_payloads, game_id=game_id)


if __name__ == "__main__":
    asyncio.run(main())
