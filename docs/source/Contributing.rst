Contributing
============

This guide provides instructions for setting up the development environment and contributing to the econagents project.

.. contents:: Table of Contents
   :depth: 2
   :local:

Setting Up the Development Environment
--------------------------------------

1.  **Clone the Repository:**
    Start by cloning the repository from GitHub:

    .. code-block:: bash

       git clone https://github.com/IBEX-TUDelft/econagents
       cd econagents

2.  **Install Poetry:**
    This project uses [Poetry](https://python-poetry.org/) for dependency management and packaging. If you don't have Poetry installed, follow the official installation guide.

3.  **Install Dependencies:**
    Once Poetry is installed, you can install the project dependencies, including development tools:

    .. code-block:: bash

       poetry install --all-extras

    This command creates a virtual environment (if one doesn't exist) and installs all required packages defined in ``pyproject.toml``, including optional groups like ``dev``, LLM provider, and observability provider dependencies.

4.  **Activate the Virtual Environment:**
    Activate the Poetry-managed virtual environment:

    .. code-block:: bash

       poetry env activate

    All subsequent commands should be run within this activated environment.

Setting Up Pre-Commit Hooks
---------------------------

We use pre-commit hooks to ensure code style consistency and catch potential issues before code is committed. The configuration is defined in ``.pre-commit-config.yaml``.

To set up the hooks, run the following command in the project root directory (within the activated virtual environment):

.. code-block:: bash

   pre-commit install

Now, the hooks will automatically run on every ``git commit``, formatting code with Ruff and performing other checks.

Running Tests
-------------

To ensure your changes don't break existing functionality, run the test suite using pytest:

.. code-block:: bash

   pytest

You can also run tests with coverage reporting:

.. code-block:: bash

   pytest --cov=econagents --cov-report=term-missing

Code Style and Linting
----------------------

We use \`Ruff <https://github.com/astral-sh/ruff>\`_ for linting and formatting. The pre-commit hooks automatically handle formatting. You can also run Ruff manually:

.. code-block:: bash

   # Check for linting errors
   ruff check .

   # Format code
   ruff format .

Configuration for Ruff is located in the ``pyproject.toml`` file.

Building Documentation
----------------------

To build the documentation locally:

1.  Navigate to the ``docs/`` directory:

    .. code-block:: bash

       cd docs

2.  Build the HTML documentation:

    .. code-block:: bash

       make html

The generated documentation will be available in the ``docs/build/html/`` directory. Open ``index.html`` in your browser to view it.

General Contribution Guidelines
-------------------------------

-   **Branching:** Create a new feature branch for your changes based on the ``main`` branch. Use a descriptive name (e.g., ``feature/add-new-agent-role``, ``fix/resolve-state-bug``).
-   **Commits:** Write clear and concise commit messages.
-   **Pull Requests:** Once your changes are complete and tested, open a pull request against the ``main`` branch. Provide a detailed description of the changes in the pull request.
-   **Code Reviews:** Be responsive to feedback during code reviews.
-   **Keep it Simple:** Adhere to the project's principles of modular design and simplicity.
-   **Documentation:** Update or add documentation (including docstrings) for any new features or changes in behavior.

Thank you for contributing to econagents! 
