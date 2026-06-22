import asyncio
import logging
from pathlib import Path

from dotenv import load_dotenv
from typing_extensions import Literal

from econagents.adapters.transport import SimpleLoginPayloadAuth
from econagents.runtime.game_runner import GameRunner, TurnBasedGameRunnerConfig
from examples.public_goods.agents import create_public_goods_agents
from examples.public_goods.server.create_game import create_game_from_specs

logger = logging.getLogger("public_goods_game")


def get_personality(player_number: int) -> Literal["cooperative", "selfish"]:
    """Get the personality type for a player."""
    return "cooperative" if player_number % 2 == 0 else "selfish"


async def main():
    """Main function to run the game."""
    logger.info("Starting Public Goods game")

    load_dotenv()

    # Configure game parameters
    num_players = 4
    initial_endowment = 20.0
    public_good_efficiency = 0.5

    game_specs = create_game_from_specs(
        num_players=num_players,
        initial_endowment=initial_endowment,
        public_good_efficiency=public_good_efficiency,
    )

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

    personalities = [get_personality(i + 1) for i in range(num_players)]
    agents = create_public_goods_agents(config, game_specs["recovery_codes"], personalities)

    runner = GameRunner(config=config, agents=agents)
    await runner.run_game()


if __name__ == "__main__":
    asyncio.run(main())
