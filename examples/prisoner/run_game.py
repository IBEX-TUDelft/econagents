import asyncio
import logging
from pathlib import Path

from dotenv import load_dotenv

from econagents.runtime.game_runner import GameRunner, TurnBasedGameRunnerConfig
from examples.prisoner.agents import create_prisoner_agents
from examples.prisoner.server.create_game import create_game_from_specs

logger = logging.getLogger("prisoners_dilemma")


async def main():
    """Main function to run the game."""
    logger.info("Starting Prisoner's Dilemma game")

    load_dotenv()

    game_specs = create_game_from_specs()

    config = TurnBasedGameRunnerConfig(
        game_id=game_specs["game_id"],
        logs_dir=Path(__file__).parent / "logs",
        prompts_dir=Path(__file__).parent / "prompts",
        log_level=logging.INFO,
        hostname="localhost",
        port=8765,
        path="",
    )
    agents = create_prisoner_agents(config, game_specs["recovery_codes"])
    runner = GameRunner(config=config, agents=agents)

    # Run the game
    await runner.run_game()


if __name__ == "__main__":
    asyncio.run(main())
