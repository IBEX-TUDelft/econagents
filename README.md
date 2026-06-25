<div align="center">
  <img src="https://raw.githubusercontent.com/IBEX-TUDelft/econagents/main/assets/logo_200w.png">
</div>

<div align="center">

![Python compat](https://img.shields.io/badge/%3E=python-3.10-blue.svg)
[![PyPi](https://img.shields.io/pypi/v/econagents.svg)](https://pypi.python.org/pypi/econagents)
[![GHA Status](https://github.com/IBEX-TUDelft/econagents/actions/workflows/tests.yaml/badge.svg?branch=main)](https://github.com/IBEX-TUDelft/econagents/actions?query=workflow%3Atests)
[![Documentation Status](https://readthedocs.org/projects/econagents/badge/?version=latest)](https://econagents.readthedocs.io/en/latest/?badge=latest)

</div>

---

# econagents

econagents is a Python library that lets you use LLM agents in economic experiments. The framework connects agents to game servers, projects server events into typed game state, asks role-specific LLM policies for actions, and sends those actions back through protocol adapters.

## Key Features

- **Agent Runtime**: Run one explicit `Agent` per simulated player.
- **Ports and Adapters**: Swap protocol codecs, transports, prompt renderers, response parsers, and state projectors.
- **Flexible Agent Customization**: Customize behavior with Jinja templates, response schemas, personas, or custom Python phase handlers.
- **Event-Driven State Management**: Project server events into typed public, private, and meta state.
- **Turn-Based and Continuous Action Support**: Handle one-shot phase decisions and repeated continuous-phase actions.

## Installation

```shell
# Install from PyPI
pip install econagents

# Or install directly from GitHub
pip install git+https://github.com/IBEX-TUDelft/econagents.git
```

## Framework Components

econagents consists of these main components:

1. **Domain Types**: `Event`, `Action`, `PhaseId`, and `AgentContext`.
2. **Ports**: Interfaces for codecs, transports, prompt rendering, response parsing, and state projection.
3. **Adapters**: IBEX envelopes, WebSocket transport, Jinja prompts, JSON response parsing, and `EventField` state projection.
4. **Roles**: Role-specific LLM policies and phase participation rules.
5. **Agents**: One runtime per simulated player.
6. **Game Runner**: Supervises agents, logging, timeout, and cleanup.

## Example Experiments

The repository includes three example games:

1. **`prisoner`**: An iterated Prisoner's Dilemma game with 5 rounds and 2 LLM agents, runs on a local python server (included).
2. **`dictator`**: A modified Dictator game with 2 LLM agents that runs on a local python server (included).
3. **`public_goods`**: A public goods game with 4 players that runs on a local python server (included).

### Running the Prisoner's Dilemma game

The simplest game to run is a version of the repeated prisoner's dilemma game that runs on your local machine.

```shell
# Run the server
uv run python examples/prisoner/server/server.py

# Run the experiment (in a separate terminal)
uv run python examples/prisoner/run_game.py
```

Note: set `OPENAI_API_KEY` before running OpenAI-backed examples.

## Documentation

For detailed guides and API reference, visit [the documentation](https://econagents.readthedocs.io/en/latest/).

You should also check out the [econagents cookbook](https://github.com/iwanalabs/econagents-cookbook/tree/main/) for more examples.
