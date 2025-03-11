Tutorial
--------

Before running an experiment, ensure you have:

1. Python 3.10+ installed
2. All dependencies installed
3. Have set up API keys for OpenAI and LangSmith

Create a ``.env`` file in your project root with the following variables:

.. code-block:: text

    LANGCHAIN_API_KEY=<your_langsmith_api_key>
    LANGSMITH_TRACING=true
    LANGSMITH_ENDPOINT="https://api.smith.langchain.com"
    LANGSMITH_PROJECT="econagents"

    OPENAI_API_KEY=<your_openai_api_key>
