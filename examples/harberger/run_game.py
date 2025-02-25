import argparse
import asyncio
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from econagents.core.game_runner import GameRunner, GameRunnerConfig
from examples.server.create_game import create_game_from_specs
from examples.harberger.manager import HarbergerAgentManager

load_dotenv()


async def run_existing_game(game_id: int) -> None:
    """Run an existing Harberger tax game."""
    # Configure the game runner
    config = GameRunnerConfig(hostname=HOSTNAME, port=PORT, log_path=LOG_PATH, games_path=GAMES_PATH)

    # Create game runner with Harberger-specific agent manager
    runner = GameRunner(config=config, agent_manager_class=HarbergerAgentManager)

    # Spawn agents for the game
    await runner.spawn_agents_for_game(game_id=game_id)


async def create_and_run_game(specs_path: Path) -> None:
    """Create and run a new Harberger tax game."""
    # Configure the game runner
    config = GameRunnerConfig(hostname=HOSTNAME, port=PORT, log_path=LOG_PATH, games_path=GAMES_PATH)

    # Create game runner with Harberger-specific agent manager
    runner = GameRunner(config=config, agent_manager_class=HarbergerAgentManager)

    # Generate a game name with timestamp
    game_name = f"harberger {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    # Create and run the game
    await runner.create_and_run_game(
        specs_path=specs_path, game_creator_func=create_game_from_specs, game_name=game_name
    )


if __name__ == "__main__":
    # Load environment variables
    HOSTNAME = os.getenv("HOSTNAME")
    PORT = os.getenv("PORT")

    # Setup paths
    BASE_DIR = Path(__file__).parent
    LOG_PATH = BASE_DIR / "logs"
    GAMES_PATH = BASE_DIR / "specs" / "games"

    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Run or create and run a Harberger tax game.")
    parser.add_argument("--game-id", type=int, help="ID of existing game to run", default=None)
    args = parser.parse_args()

    if args.game_id is not None:
        # Run existing game
        asyncio.run(run_existing_game(game_id=args.game_id))
    else:
        # Create and run new game
        specs_path = BASE_DIR / "specs/harberger.json"
        asyncio.run(create_and_run_game(specs_path))
