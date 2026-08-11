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

Optional Dependencies
---------------------

The base install ships with the OpenAI client. It powers both the default
OpenAI provider and the OpenRouter provider. Other providers and observability
backends are available as extras so you can pick what you need.

LLM Providers
~~~~~~~~~~~~~

- ``openrouter``: For routing requests across OpenRouter's model catalog. Set
  ``OPENROUTER_API_KEY`` and use ``ChatOpenRouter`` with an OpenRouter model
  slug:

   .. code-block:: python

      from econagents.adapters.llm import ChatOpenRouter

      llm = ChatOpenRouter(model_name="anthropic/claude-sonnet-4")

  The optional ``site_url`` and ``app_name`` constructor arguments set
  OpenRouter's app-attribution headers. No installation extra is needed.

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
