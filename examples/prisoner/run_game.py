import asyncio
import logging
from pathlib import Path

from dotenv import load_dotenv

from econagents.core.game_runner import GameRunner, TurnBasedGameRunnerConfig
from examples.prisoner.manager import PDManager
from examples.prisoner.server.create_game import create_game_from_specs
from examples.prisoner.state import PDGameState

logger = logging.getLogger("prisoners_dilemma")


async def main():
    """Main function to run the game."""
    logger.info("Starting Prisoner's Dilemma game")

    load_dotenv()

    game_specs = create_game_from_specs()
    login_payloads = [
        {"type": "join", "gameId": game_specs["game_id"], "recovery": code} for code in game_specs["recovery_codes"]
    ]

    # Create config and runner
    config = TurnBasedGameRunnerConfig(
        # Game configuration
        game_id=game_specs["game_id"],
        logs_dir=Path(__file__).parent / "logs",
        prompts_dir=Path(__file__).parent / "prompts",
        log_level=logging.INFO,
        # Server configuration
        hostname="localhost",
        port=8765,
        path="wss",
        # State configuration
        state_class=PDGameState,
        # Phase transition configuration
        phase_transition_event="round-started",
        phase_identifier_key="round",
        # Observability configuration
        observability_provider="langfuse",
    )
    agents = [
        PDManager(
            game_id=game_specs["game_id"],
            auth_mechanism_kwargs=payload,
        )
        for payload in login_payloads
    ]
    runner = GameRunner(config=config, agents=agents)

    # Run the game
    await runner.run_game()


if __name__ == "__main__":
    asyncio.run(main())
