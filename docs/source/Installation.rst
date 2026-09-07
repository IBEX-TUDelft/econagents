Installation
============

econagents requires Python ``>=3.10`` and can be installed from pypi via:

.. code-block:: bash

   python -m pip install econagents


To install directly from GitHub, you can run:

.. code-block:: bash

   python -m pip install git+https://github.com/IBEX-TUDelft/econagents.git

For development, it's recommended to use uv:

.. code-block:: bash

   git clone https://github.com/IBEX-TUDelft/econagents.git
   cd econagents
   uv sync --all-extras --all-groups

Note that `uv <https://docs.astral.sh/uv/>`_ is used to create and manage the virtual environment for the project development. If you are not planning to contribute to the project, you can install the dependencies using your preferred package manager.

The runnable examples under ``examples/`` are not part of the PyPI package. To run them, clone the repository and install it with the ``examples`` extra:

.. code-block:: bash

   git clone https://github.com/IBEX-TUDelft/econagents.git
   cd econagents
   python -m venv .venv && source .venv/bin/activate
   pip install -e ".[examples]"

On Debian and Ubuntu the system Python ships without ``venv`` and ``pip``; run ``sudo apt install python3-venv python3-pip`` first.

Optional Dependencies
---------------------

The base install ships with the OpenAI client. It powers both the default
OpenAI provider and the OpenRouter provider. Other providers and observability
backends are available as extras so you can pick what you need.

Using OpenRouter
~~~~~~~~~~~~~~~~

OpenRouter needs no extra: the base install already includes ``ChatOpenRouter``.
Set ``OPENROUTER_API_KEY`` and pass an OpenRouter model slug:

.. code-block:: python

   from econagents.adapters.llm import ChatOpenRouter

   llm = ChatOpenRouter(model_name="anthropic/claude-sonnet-4")

The optional ``site_url`` and ``app_name`` constructor arguments set
OpenRouter's app-attribution headers. ``examples/prisoner/prisoner_openrouter.yaml``
is a complete YAML experiment that uses it.

LLM Providers
~~~~~~~~~~~~~

- ``examples``: Dependencies needed to run the scripts under ``examples/``

   .. code-block:: bash

      pip install econagents[examples]

- ``ollama``: For using locally-hosted Ollama models

   .. code-block:: bash

      pip install econagents[ollama]

Observability Providers
~~~~~~~~~~~~~~~~~~~~~~~

For tracing and monitoring your LLM calls:

- ``langsmith``: For using LangSmith to track and analyze LLM calls

   .. code-block:: bash

      pip install econagents[langsmith]

- ``langfuse``: For using LangFuse for observability

   .. code-block:: bash

      pip install econagents[langfuse]

Convenience Installations
~~~~~~~~~~~~~~~~~~~~~~~~~

You can combine multiple optional dependencies:

- Standard installation (adds LangSmith on top of the default OpenAI client):

   .. code-block:: bash

      pip install econagents[standard]

- All optional dependencies:

   .. code-block:: bash

      pip install econagents[all]

- Custom combinations:

   .. code-block:: bash

      pip install econagents[ollama,langfuse]

Runtime Dependencies
--------------------

The package depends on the following libraries:

- ``pydantic``: For data validation and parsing
- ``requests``: For HTTP requests
- ``websockets``: For WebSocket connections
- ``jinja2``: For rendering prompt templates
- ``pyyaml``: For parsing experiment config files
- ``openai``: Client for the OpenAI and OpenRouter LLM providers

Known Issues
------------

1. Organizational security policies may break the websocket connection. If you keep getting ``1006, ConnectionClosed`` errors try to install the package in another device.
2. Notebooks and `asyncio` may not play well together. When you cancel a game running in a notebook, the websocket connection may not be closed properly. Close the notebook kernel before running another game.
3. OpenRouter workspaces can restrict which models are allowed. If a request fails with a ``404`` whose message mentions ``guardrail``, the model is blocked for your workspace; pick another ``model_name`` or adjust the guardrail settings in the OpenRouter dashboard.
