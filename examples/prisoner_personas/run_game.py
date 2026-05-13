"""Code-driven entry point for the persona-driven prisoner experiment.

Mirrors ``examples/prisoner/run_game.py`` but constructs each agent's manager
with an explicit persona loaded by id. Personas are resolved from the local
``./personas`` directory first, falling back to the bundled library shipped
inside ``econagents.personas``.

Reuses the local game server and state class from ``examples/prisoner/``.

Server (in another terminal):

    uv run python examples/prisoner/server/server.py

Then this:

    uv run python examples/prisoner_personas/run_game.py
"""

import asyncio
import logging
from pathlib import Path

from dotenv import load_dotenv

from econagents.core.game_runner import GameRunner, TurnBasedGameRunnerConfig
from econagents.personas import load_persona
from examples.prisoner.server.create_game import create_game_from_specs
from examples.prisoner.state import PDGameState
from examples.prisoner_personas.manager import PDManager

logger = logging.getLogger("prisoners_dilemma_personas")

PERSONAS_DIR = Path(__file__).parent / "personas"

# One persona id per agent. The order matches the recovery codes returned
# by ``create_game_from_specs`` (agent 1, agent 2, ...).
PERSONA_IDS = [
    "conditional-cooperator",  # bundled archetype
    "marcus-strategic-44",  # user-authored composite under ./personas
]


async def main() -> None:
    logger.info("Starting persona-driven Prisoner's Dilemma game")
    load_dotenv()

    game_specs = create_game_from_specs()
    login_payloads = [
        {"type": "join", "gameId": game_specs["game_id"], "recovery": code}
        for code in game_specs["recovery_codes"]
    ]

    config = TurnBasedGameRunnerConfig(
        game_id=game_specs["game_id"],
        logs_dir=Path(__file__).parent / "logs",
        prompts_dir=Path(__file__).parent / "prompts",
        log_level=logging.INFO,
        hostname="localhost",
        port=8765,
        path="wss",
        state_class=PDGameState,
        phase_transition_event="round-started",
        phase_identifier_key="round",
        observability_provider="langsmith",
    )

    agents = [
        PDManager(
            game_id=game_specs["game_id"],
            auth_mechanism_kwargs=payload,
            persona=load_persona(persona_id, user_dir=PERSONAS_DIR),
        )
        for payload, persona_id in zip(login_payloads, PERSONA_IDS)
    ]

    runner = GameRunner(config=config, agents=agents)
    await runner.run_game()


if __name__ == "__main__":
    asyncio.run(main())
