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

Dependencies
------------

The project depends on the following packages:

- ``openai``: For LLM interactions
- ``langsmith``: For tracing and monitoring
- ``websockets``: For WebSocket connections
- ``pydantic``: For data validation and parsing
- ``requests``: For HTTP requests

For now, we require ``openai`` and ``langsmith`` to be installed. We plan to add more model providers and monitoring tools in the future. Users will be able to choose their preferred provider and monitoring tool, and the framework will be designed to be compatible with most popular LLM providers.
