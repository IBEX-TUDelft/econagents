import asyncio
import logging
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from econagents.core.game_runner import GameRunner, GameRunnerConfig
from examples.prisoner.manager import PrisonersDilemmaManager
from examples.server.prisoner.create_game import create_game_from_specs

logger = logging.getLogger("prisoners_dilemma")


async def main():
    """Main function to run the game."""
    logger.info("Starting Prisoner's Dilemma game")

    load_dotenv()

    # Load environment variables
    hostname = "localhost"
    port = 8765

    # Setup paths
    base_dir = Path(__file__).parent
    log_path = base_dir / "logs"
    games_path = base_dir / "specs" / "games"
    specs_path = base_dir / "specs" / "prisoner.json"

    # Ensure directories exist
    log_path.mkdir(exist_ok=True)
    games_path.mkdir(exist_ok=True, parents=True)

    # Create config and runner
    config = GameRunnerConfig(hostname=hostname, port=port, log_path=log_path, games_path=games_path)
    runner = GameRunner(config=config, agent_manager_class=PrisonersDilemmaManager)

    # Create game name with timestamp
    game_name = f"prisoners_dilemma_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"

    # Run the game
    await runner.create_and_run_game(
        specs_path=specs_path, game_creator_func=create_game_from_specs, game_name=game_name
    )


if __name__ == "__main__":
    asyncio.run(main())
