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

econagents is a Python library for running economic experiments with LLM agents as participants. You describe the game — roles, prompts, and game state — and econagents connects one agent per player to your experiment server, keeps each agent's view of the game up to date, queries an LLM for decisions each phase, and logs everything for analysis.

## What you can do with it

- **Run classic economic games with LLM players**: Prisoner's Dilemma, Dictator, Public Goods, and a continuous double auction shipped as runnable examples with local servers included.
- **Agent runtime**: Run one explicit `Agent` per simulated player.
- **Define experiments in YAML**: Declare roles, per-phase prompts (Jinja templates), agent assignments, and game state in a single config file, then launch with `run_experiment_from_yaml` — no framework code required for standard setups.
- **Ports and Adapters**: Swap protocol codecs, transports, prompt renderers, response parsers, and state projectors.
- **Flexible agent customization**: Customize behavior with Jinja templates, response schemas, personas, or custom Python phase handlers; give agents different strategies and personas to study heterogeneous populations.
- **Event-driven state management**: Project server events into typed public, private, and meta state.
- **Hosted and local models**: Use OpenAI, OpenRouter, or run local models via Ollama; configurable per role so different players can run on different models.
- **Connect to your own experiment server**: Agents talk to game servers over WebSockets. The default protocol targets IBEX-style envelopes, and codecs, transports, and parsers are swappable for other servers.
- **Turn-based and continuous action support**: Handle one-shot phase decisions and repeated actions within continuous market phases (as in the double auction example).
- **Trace and analyze runs**: Per-agent logs are written for every game, with optional LangSmith or Langfuse tracing of all LLM calls.

## Installation

```shell
# Install from PyPI
pip install econagents

# Or install directly from GitHub
pip install git+https://github.com/IBEX-TUDelft/econagents.git
```

## Quickstart

The fastest way to see it in action is the repeated Prisoner's Dilemma, which runs entirely on your machine (set `OPENAI_API_KEY` first):

```shell
# Run the game server
uv run python examples/prisoner/server/server.py

# Run the experiment (in a separate terminal)
uv run python examples/prisoner/run_game.py
```

Two LLM agents play five rounds against each other; per-agent logs land in `examples/prisoner/logs/`.

Most of the experiment lives in a YAML file. Here's a condensed look at `examples/prisoner/prisoner.yaml`:

```yaml
roles:
  - role_id: 1
    name: "cooperator"
    llm_type: "ChatOpenAI"
    llm_params:
      model_name: "gpt-5.4-mini"
    prompts:
      - system: |
          {% include "_partials/game_description.jinja2" %}
          You will generally cooperate with the other prisoner.
      - user: |
          {% include "_partials/game_history.jinja2" %}
          {% include "_partials/game_instructions.jinja2" %}
  - role_id: 2
    name: "defector"
    # ...

agents:
  - id: 1
    role_id: 1
  - id: 2
    role_id: 2

state:
  public_information:
    - name: "history"
      type: "list"
      default_factory: "list"
```

Prompts are Jinja templates rendered against the live game state, so agents always see the current round, their payoffs, and the history you choose to expose. Running it is one call:

```python
from econagents.adapters.config import run_experiment_from_yaml

await run_experiment_from_yaml("prisoner.yaml", login_payloads, game_id=game_id)
```

When YAML isn't flexible enough — custom phase logic, bespoke state handling — you can drop down to Python and compose the same building blocks directly (see `examples/prisoner/run_game.py`).

## Example experiments

| Example | What it shows |
|---|---|
| [`prisoner`](examples/prisoner/) | Iterated Prisoner's Dilemma, 2 agents, 5 rounds, local server included |
| [`prisoner_personas`](examples/prisoner_personas/) | Same game, but each agent plays a distinct persona |
| [`dictator`](examples/dictator/) | Modified Dictator game with 2 agents, local server included |
| [`public_goods`](examples/public_goods/) | Public goods game with 4 players, local server included |
| [`continuous_double_auction`](examples/continuous_double_auction/) | LLM-backed traders in a continuous market phase |

More examples are in the [econagents cookbook](https://github.com/iwanalabs/econagents-cookbook/tree/main/).

## How it works

Each simulated player is an `Agent` that connects to the game server over a transport (WebSockets by default), decodes server events through a protocol codec, and projects them into typed public, private, and meta state. When a phase requires a decision, the agent's role renders prompts from that state, queries its LLM, parses the response into an action, and sends it back to the server. A `GameRunner` supervises all agents, logging, timeouts, and cleanup. Every piece — codec, transport, prompt renderer, response parser, state projector — sits behind a port interface, so you can swap implementations to fit your server or workflow.

To route a YAML role through OpenRouter, set `OPENROUTER_API_KEY` and use an
OpenRouter model slug:

```yaml
roles:
  - role_id: 1
    name: "player"
    llm_type: "ChatOpenRouter"
    llm_params:
      model_name: "anthropic/claude-sonnet-4"
```

`ChatOpenRouter` supports structured outputs, tool calling, normalized
reasoning controls, provider routing options, and optional app attribution.

## Documentation

For detailed guides and API reference, visit [the documentation](https://econagents.readthedocs.io/en/latest/).
