Installation
============

econagents requires Python ``>=3.10`` and can be installed from pypi via:

.. code-block:: bash

   python -m pip install econagents


To install directly from GitHub, you can run:

.. code-block:: bash

   python -m pip install git+https://github.com/iwanalabs/econagents.git

For development, its recommended to use Poetry:

.. code-block:: bash

   git clone https://github.com/iwanalabs/econagents.git
   cd econagents
   poetry install

Note that [Poetry](https://python-poetry.org/) is used to create and manage the virtual environment for the project development. If you are not planning to contribute to the project, you can install the dependencies using your preferred package manager.

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

- Default installation (includes OpenAI and LangSmith):

   .. code-block:: bash

      pip install econagents[default]

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
