import asyncio
import logging
from pathlib import Path

from dotenv import load_dotenv

from econagents.core.game_runner import GameRunner, TurnBasedGameRunnerConfig
from examples.dictator.manager import DictatorManager, ReceiverManager
from examples.dictator.server.create_game import create_game_from_specs
from examples.dictator.state import DGameState

logger = logging.getLogger("dictator_game")


async def main():
    """Main function to run the game."""
    logger.info("Starting Dictator game")

    load_dotenv()

    game_specs = create_game_from_specs(money_available=10.0, exchange_rate=3.0)
    login_payloads = [
        {"type": "join", "gameId": game_specs["game_id"], "recovery": code}
        for code in game_specs["recovery_codes"]
    ]

    config = TurnBasedGameRunnerConfig(
        game_id=game_specs["game_id"],
        logs_dir=Path(__file__).parent / "logs",
        prompts_dir=Path(__file__).parent / "prompts",
        log_level=logging.DEBUG,
        hostname="localhost",
        port=8765,
        path="wss",
        state_class=DGameState,
        phase_transition_event="phase-started",
        phase_identifier_key="phase",
        observability_provider="langsmith",
    )

    agents = [
        DictatorManager(  # Agent 1 is always the Dictator
            game_id=game_specs["game_id"],
            auth_mechanism_kwargs=login_payloads[0],
        ),
        ReceiverManager(  # Agent 2 is always the Receiver
            game_id=game_specs["game_id"],
            auth_mechanism_kwargs=login_payloads[1],
        ),
    ]

    runner = GameRunner(config=config, agents=agents)
    await runner.run_game()


if __name__ == "__main__":
    asyncio.run(main())
