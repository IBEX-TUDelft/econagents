import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from econagents.runtime.game_runner import GameRunner, HybridGameRunnerConfig
from examples.continuous_double_auction.agents import MARKET_PHASE, create_cda_agents
from examples.continuous_double_auction.server.create_game import create_game_from_specs

logger = logging.getLogger("continuous_double_auction")

MARKET_DURATION_SECONDS = 60
SUMMARY_DURATION_SECONDS = 2
ACTION_DELAY_SECONDS = 8


async def main() -> None:
    """Run a local continuous double auction with LLM-backed traders."""
    logger.info("Starting Continuous Double Auction example")
    env_path = Path(__file__).resolve().parents[2] / ".env"
    load_dotenv(env_path, override=True)
    logger.info(
        "Loaded environment from %s; OPENAI_API_KEY is %s",
        env_path,
        "set" if os.getenv("OPENAI_API_KEY") else "not set",
    )

    game_specs = create_game_from_specs(
        market_duration=MARKET_DURATION_SECONDS,
        summary_duration=SUMMARY_DURATION_SECONDS,
    )

    config = HybridGameRunnerConfig(
        game_id=game_specs["game_id"],
        logs_dir=Path(__file__).parent / "logs",
        prompts_dir=Path(__file__).parent / "prompts",
        log_level=logging.DEBUG,
        hostname="localhost",
        port=8766,
        path="",
        continuous_phases=[MARKET_PHASE],
        min_action_delay=ACTION_DELAY_SECONDS,
        max_action_delay=ACTION_DELAY_SECONDS,
        max_game_duration=game_specs["market_duration"] + game_specs["summary_duration"] + 45,
        observability_provider="langsmith",
    )
    agents = create_cda_agents(config, game_specs["recovery_codes"])
    runner = GameRunner(config=config, agents=agents)

    await runner.run_game()


if __name__ == "__main__":
    asyncio.run(main())
