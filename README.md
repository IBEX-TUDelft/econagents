<div align="center">
  <img src="https://raw.githubusercontent.com/iwanalabs/econagents/main/assets/logo_200w.png">
</div>

<div align="center">

![Python compat](https://img.shields.io/badge/%3E=python-3.10-blue.svg)
[![PyPi](https://img.shields.io/pypi/v/econagents.svg)](https://pypi.python.org/pypi/econagents)
[![GHA Status](https://github.com/iwanalabs/econagents/actions/workflows/tests.yaml/badge.svg?branch=main)](https://github.com/iwanalabs/econagents/actions?query=workflow%3Atests)
[![Documentation Status](https://readthedocs.org/projects/econagents/badge/?version=latest)](https://econagents.readthedocs.io/en/latest/?badge=latest)

</div>

---

# econagents

econagents is a Python library that lets you use LLM agents in economic experiments. The framework connects LLM agents to game servers through WebSockets and provides a flexible architecture for designing, customizing, and running economic simulations.

## Installation

```shell
# Install from PyPI
pip install econagents

# Or install directly from GitHub
pip install git+https://github.com/iwanalabs/econagents.git
```

## Framework Components

econagents consists of four key components:

1. **Agent Roles**: Define player roles with customizable behaviors using a flexible prompt system.
2. **Game State**: Hierarchical state management with automatic event-driven updates.
3. **Agent Managers**: Manage agent connections to game servers and handle event processing.
4. **Game Runner**: Orchestrates experiments by gluing together the other components.

## Example Experiments

The repository includes three example games:

1. **`prisoner`**: An iterated Prisoner's Dilemma game with 5 rounds and 2 LLM agents.
2. **`tudeflt/harberger`**: A Harberger Tax simulation with LLM agents.
3. **`tudeflt/futarchy`**: A Futarchy simulation with LLM agents.

### Running the Prisoner's Dilemma Experiment

```shell
# Run the server
python examples/server/prisoner/server.py

# Run the experiment (in a separate terminal)
python examples/prisoner/run_game.py
```

## Key Features

- **Flexible Agent Customization**: Customize agent behavior with Jinja templates or custom Python methods
- **Event-Driven State Management**: Automatically update game state based on server events
- **Turn-Based and Continuous Action Support**: Handle both turn-based games and continuous action phases
- **LangChain Integration**: Built-in support for LangChain's agent capabilities

## Documentation

For detailed guides and API reference, visit [the documentation](https://econagents.readthedocs.io/en/latest/).
