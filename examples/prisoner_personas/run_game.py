"""Code-driven entry point for the persona-driven prisoner experiment.

Mirrors ``examples/prisoner/run_game.py`` but constructs each agent's manager
with an explicit persona loaded by id. Personas are resolved from the local
``./personas`` directory first, falling back to the bundled library shipped
inside ``econagents.personas``.

Reuses the local game server and state class from ``examples/prisoner/``.

Server (in another terminal):

    uv run python examples/prisoner/server/server.py

Then this:

    uv run python examples/prisoner_personas/run_game.py \
        --game-id 1 \
        --persona conditional-cooperator --persona marcus-strategic-44 \
        --recovery-code CODE1 --recovery-code CODE2
"""

import argparse
import asyncio
import logging
from pathlib import Path

from dotenv import load_dotenv

from econagents.core.game_runner import GameRunner, TurnBasedGameRunnerConfig
from econagents.personas import load_persona
from examples.prisoner.manager import PDManager
from examples.prisoner.state import PDGameState

logger = logging.getLogger("prisoners_dilemma_personas")

PERSONAS_DIR = Path(__file__).parent / "personas"


async def main(
    game_id: int,
    recovery_codes: list[str],
    personas: list[str],
    hostname: str,
    port: int,
) -> None:
    logger.info("Starting persona-driven Prisoner's Dilemma game")
    load_dotenv()

    config = TurnBasedGameRunnerConfig(
        game_id=game_id,
        logs_dir=Path(__file__).parent / "logs",
        prompts_dir=Path(__file__).parent / "prompts",
        log_level=logging.INFO,
        hostname=hostname,
        port=port,
        path="",
        state_class=PDGameState,
    )

    agents = []
    for i, (recovery_code, persona_id) in enumerate(zip(recovery_codes, personas)):
        agent = PDManager(
            game_id=game_id,
            auth_mechanism_kwargs={
                "meta": {"type": "join"},
                "payload": {"recovery": recovery_code},
            },
        )
        if persona_id:
            agent.agent_role.persona = load_persona(persona_id, user_dir=PERSONAS_DIR)
        agents.append(agent)

    runner = GameRunner(config=config, agents=agents)
    await runner.run_game()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the persona-driven Prisoner's Dilemma experiment."
    )
    parser.add_argument(
        "--game-id",
        type=int,
        required=True,
        help="Id of the game to join.",
    )
    parser.add_argument(
        "--persona",
        dest="personas",
        action="append",
        default=[],
        metavar="PERSONA_ID",
        help="Persona id for an agent. Repeat once per agent, in agent order.",
    )
    parser.add_argument(
        "--recovery-code",
        dest="recovery_codes",
        action="append",
        required=True,
        metavar="CODE",
        help="Recovery code for an agent. Repeat once per agent, in agent order.",
    )
    parser.add_argument(
        "--hostname",
        default="localhost",
        help="Game server hostname.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=3000,
        help="Game server port.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    """
    How to run:
      uv run python examples/prisoner_personas/run_game.py \
      --game-id 1 \
      --persona conditional-cooperator \
      --persona marcus-strategic-44 \
      --recovery-code CODE1 \
      --recovery-code CODE2
    """
    args = parse_args()
    # Pad personas with empty strings so the list is always as long as recovery_codes.
    personas = args.personas + [""] * (len(args.recovery_codes) - len(args.personas))
    asyncio.run(
        main(
            game_id=args.game_id,
            recovery_codes=args.recovery_codes,
            personas=personas,
            hostname=args.hostname,
            port=args.port,
        )
    )
