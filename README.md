<div align="center">
  <img src="https://raw.githubusercontent.com/iwanalabs/ecoagents/main/assets/logo_200w.png">
</div>

<div align="center">

![Python compat](https://img.shields.io/badge/%3E=python-3.10-blue.svg)
[![PyPi](https://img.shields.io/pypi/v/ecoagents.svg)](https://pypi.python.org/pypi/ecoagents)
[![GHA Status](https://github.com/iwanalabs/ecoagents/actions/workflows/tests.yaml/badge.svg?branch=main)](https://github.com/iwanalabs/ecoagents/actions?query=workflow%3Atests)
[![Documentation Status](https://readthedocs.org/projects/econagents/badge/?version=latest)](https://econagents.readthedocs.io/en/latest/?badge=latest)

</div>

---

econagents is a Python library for creating and running economic experiments.

# Installation

Follow these steps to get started:

1. Create a virtual environment and install the dependencies using poetry:

```shell
poetry install
```

2. Copy the `.env.example` file to `.env` and fill in the values.

## Using the example experiments

There are currently three example experiments you can use to get started:

1. `prisoner`: A simple experiment of an iterated Prisoner's Dilemma of 5 rounds using 2 LLM agents.
2. `harberger`: A heavily customized experiment of a Harberger Tax game played by LLM agents.
3. `harberge_lite`: A simplified version of the Harberger Tax game.

The example experiments are located in the `examples` directory.

The server to run the `prisoner` experiment is located in the `server` directory. For the `harberger` and `harberge_lite` experiments, the server implementation is not provided yet.

## Running the experiments

For `prisoner` you first must run the server and then run the experiment:

```shell
# Run the server
python examples/server/prisoner/server.py

# Run the experiment (on a separate terminal)
python examples/prisoner/run_game.py
```

For the `harberger` experiment, you can run the experiment by executing the `run_game.py` script in the respective experiment directory.

```shell
python examples/harberger/run_game.py
```

For the `harberger_lite` experiment, you can use the notebook `examples/harberger_lite/run_game.ipynb`.
