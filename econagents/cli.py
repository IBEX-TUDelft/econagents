import argparse
import asyncio
import sys
import json
from pathlib import Path
from typing import Dict, List, Any

from econagents.config_parser.base import BaseConfigParser


async def async_main(args: argparse.Namespace):
    """Asynchronous main function to run the experiment."""
    config_path = Path(args.config_path).resolve()
    login_payloads_path = Path(args.login_payloads_file).resolve()

    if not config_path.is_file():
        print(f"Error: Configuration file not found at {config_path}", file=sys.stderr)
        sys.exit(1)

    if not login_payloads_path.is_file():
        print(f"Error: Login payloads file not found at {login_payloads_path}", file=sys.stderr)
        sys.exit(1)

    try:
        # Load configuration using the base parser
        parser = BaseConfigParser(config_path)
        config = parser.config
    except Exception as e:
        print(f"Error loading or parsing config file {config_path}: {e}", file=sys.stderr)
        sys.exit(1)

    login_payloads: List[Dict[str, Any]] = []  # Initialize empty list
    try:
        with open(login_payloads_path, "r") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()  # Remove leading/trailing whitespace
                if not line:  # Skip empty lines
                    continue
                try:
                    payload = json.loads(line)
                    if not isinstance(payload, dict):
                        raise ValueError("Each line must be a valid JSON object.")
                    login_payloads.append(payload)
                except json.JSONDecodeError as e:
                    print(f"Error decoding JSON on line {line_num} in {login_payloads_path}: {e}", file=sys.stderr)
                    sys.exit(1)
                except ValueError as e:
                    print(f"Error processing line {line_num} in {login_payloads_path}: {e}", file=sys.stderr)
                    sys.exit(1)

        if not login_payloads:  # Check if any payloads were loaded
            print(f"Error: No valid login payloads found in {login_payloads_path}", file=sys.stderr)
            sys.exit(1)

    except Exception as e:
        print(f"Error reading login payloads file {login_payloads_path}: {e}", file=sys.stderr)
        sys.exit(1)

    # Ensure the number of payloads matches the number of agents defined
    num_defined_agents = len(config.agents)
    if len(login_payloads) != num_defined_agents:
        print(
            f"Error: Number of login payloads ({len(login_payloads)}) in {login_payloads_path} "
            f"does not match the number of agents defined in the config ({num_defined_agents}).",
            file=sys.stderr,
        )
        sys.exit(1)

    # Extract gameId from the first payload for display purposes (assuming all payloads are for the same game)
    # Add basic check to ensure payloads exist and have gameId
    game_id_display = "N/A"
    if login_payloads and isinstance(login_payloads[0], dict) and "gameId" in login_payloads[0]:
        game_id_display = login_payloads[0]["gameId"]

    print(f"Starting experiment '{config.name}' with Game ID: {game_id_display}...")
    print(f"Using config: {config_path}")
    print(f"Using login payloads from: {login_payloads_path}")
    print(f"Number of agents: {len(login_payloads)}")

    try:
        await parser.run_experiment(login_payloads)
        print("Experiment finished.")
    except Exception as e:
        print(f"Error running experiment: {e}", file=sys.stderr)
        sys.exit(1)


def run_cli():
    """Entry point function for the CLI script."""
    parser = argparse.ArgumentParser(
        description=(
            "Economic Agents CLI - Run experiments with AI agents in economic simulations.\n\n"
            "Example usage:\n"
            "  econagents run config.yaml --login-payloads-file payloads.jsonl\n\n"
            "The config file should be a YAML file defining the experiment setup.\n"
            "The login payloads file should be a JSONL file with login credentials for each agent."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command", required=True, help="Available commands")

    # --- Run Command ---
    run_parser = subparsers.add_parser(
        "run", 
        help="Run an experiment defined by a YAML configuration file.",
        description=(
            "Run an economic agent experiment using the specified configuration.\n\n"
            "Example:\n"
            "  econagents run experiments/market_sim.yaml --login-payloads-file credentials.jsonl"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    run_parser.add_argument(
        "config_path", 
        type=str, 
        help="Path to the experiment configuration YAML file that defines the agent behaviors and experiment parameters."
    )
    run_parser.add_argument(
        "--login-payloads-file",
        required=True,
        type=str,
        help="Path to a JSON Lines (.jsonl) file containing login credentials for each agent, one per line."
    )

    args = parser.parse_args()

    if args.command == "run":
        try:
            asyncio.run(async_main(args))
        except KeyboardInterrupt:
            print("\nExperiment interrupted by user.")
            sys.exit(0)


if __name__ == "__main__":
    run_cli()
