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

econagents is designed to be modular, allowing you to install only the dependencies you need.
The core package is lightweight, and you can add optional dependencies based on your use case.

LLM Providers
~~~~~~~~~~~~~

econagents supports multiple LLM providers through optional dependencies:

- ``openai``: For using OpenAI models like GPT-4

   .. code-block:: bash

      pip install econagents[openai]

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

- Standard installation (includes OpenAI and LangSmith):

   .. code-block:: bash

      pip install econagents[standard]

- All optional dependencies:

   .. code-block:: bash

      pip install econagents[all]

- Custom combinations:

   .. code-block:: bash

      pip install econagents[openai,langfuse]

Core Dependencies
-----------------

The core package depends on the following packages:

- ``pydantic``: For data validation and parsing
- ``requests``: For HTTP requests
- ``websockets``: For WebSocket connections
- ``jinja2``: For rendering prompt templates
- ``pyyaml``: For parsing experiment config files

Known Issues
------------

1. Organizational security policies may break the websocket connection. If you keep getting ``1006, ConnectionClosed`` errors try to install the package in another device.
2. Notebooks and `asyncio` may not play well together. When you cancel a game running in a notebook, the websocket connection may not be closed properly. Close the notebook kernel before running another game.
