import asyncio
import logging
from pathlib import Path

from dotenv import load_dotenv

from econagents.adapters.transport import SimpleLoginPayloadAuth
from econagents.runtime.game_runner import GameRunner, TurnBasedGameRunnerConfig
from examples.dictator.agents import create_dictator_agents
from examples.dictator.server.create_game import create_game_from_specs

logger = logging.getLogger("dictator_game")


async def main():
    """Main function to run the game."""
    logger.info("Starting Dictator game")

    load_dotenv()

    game_specs = create_game_from_specs(money_available=10.0, exchange_rate=3.0)

    config = TurnBasedGameRunnerConfig(
        game_id=game_specs["game_id"],
        logs_dir=Path(__file__).parent / "logs",
        prompts_dir=Path(__file__).parent / "prompts",
        log_level=logging.DEBUG,
        hostname="localhost",
        port=8765,
        path="wss",
        auth_mechanism=SimpleLoginPayloadAuth(),
        phase_transition_event="phase-started",
        phase_identifier_key="phase",
        observability_provider="langsmith",
    )

    agents = create_dictator_agents(config, game_specs["recovery_codes"])

    runner = GameRunner(config=config, agents=agents)
    await runner.run_game()


if __name__ == "__main__":
    asyncio.run(main())
