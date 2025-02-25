Customizing Agents
================

This guide explains how to customize agent behavior for different phases in the econagents framework, leveraging the flexible architecture of the ``Agent`` class.

.. contents:: Table of Contents
   :depth: 3
   :local:

Agent Architecture Overview
---------------------------

The ``Agent`` class in the economic-agents framework provides a flexible system for handling different phases in turn-based experiments. It allows for:

1. Default behavior for all phases
2. Custom handlers for specific phases
3. Custom prompt generators for specific phases
4. Custom response parsers for specific phases

This architecture makes it easy to create agents with phase-specific behaviors while maintaining a clean and organized codebase.

Phase-Specific Customization Methods
------------------------------------

There are four main aspects of agent behavior that can be customized per phase:

1. **System Prompts**: Define the agent's role and general instructions
2. **User Prompts**: Provide phase-specific instructions and context
3. **Response Parsers**: Process the LLM's response for a specific phase
4. **Phase Handlers**: Implement custom logic for handling a phase

For each of these aspects, you have multiple ways to implement customization.

Customization Approaches
------------------------

Method 1: Phase-Specific Methods
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The simplest approach is to define methods with specific naming patterns in your agent subclass:

.. code-block:: python

    class YourAgent(Agent):
        role = 1
        name = "YourAgent"
        task_phases = [2, 6, 8]

        def get_phase_2_system_prompt(self, state):
            """Custom system prompt for phase 2."""
            return "You are an economic agent in phase 2..."

        def get_phase_6_user_prompt(self, state):
            """Custom user prompt for phase 6."""
            return f"Current market state: {state.public_information.market_state}..."

        def parse_phase_8_llm_response(self, response, state):
            """Custom response parser for phase 8."""
            # Custom parsing logic
            return parsed_data

        def handle_phase_3(self, phase, state):
            """Custom handler for phase 2."""
            # Custom phase handling logic
            return result

The Agent class automatically detects these methods and registers them for the appropriate phases.

Method 2: Explicit Registration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

You can also explicitly register handlers in your agent's ``__init__`` method:

.. code-block:: python

    class YourAgent(Agent):
        role = 1
        name = "YourAgent"
        task_phases = [2, 6, 8]

        def __init__(self, logger, llm, game_id, prompts_path):
            super().__init__(logger, llm, game_id, prompts_path)

            # Register custom handlers
            self.register_system_prompt_handler(2, self.custom_system_prompt)
            self.register_user_prompt_handler(6, self.custom_user_prompt)
            self.register_response_parser(8, self.custom_response_parser)
            self.register_phase_handler(2, self.custom_phase_handler)

        def custom_system_prompt(self, state):
            return "Custom system prompt for phase 2..."

        def custom_user_prompt(self, state):
            return "Custom user prompt for phase 6..."

        def custom_response_parser(self, response, state):
            return parsed_data

        async def custom_phase_handler(self, phase, state):
            return result

Method 3: Template-Based Prompts
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

For simpler customizations, you can use Jinja2 templates stored in the ``prompts/`` directory:

.. code-block:: text

    prompts/
    ├── your_agent_system.jinja2                # Default system prompt
    ├── your_agent_system_phase_2.jinja2        # Phase-specific system prompt
    ├── your_agent_user_phase_6.jinja2          # Phase-specific user prompt
    └── all_user_phase_8.jinja2                 # Shared prompt for all agents

The Agent class will automatically look for these files and use them to generate prompts.

Prompt Resolution Logic
-----------------------

When generating system or user prompts for a phase, the Agent class follows a specific cascading resolution order. This applies only to prompt generation, not the overall phase handling logic.

For both system and user prompts, the resolution order is:

1. **Registered prompt handler**: A handler registered via ``register_system_prompt_handler`` or ``register_user_prompt_handler``
2. **Phase-specific method**: A method with naming pattern ``get_phase_{phase_number}_system_prompt`` or ``get_phase_{phase_number}_user_prompt``
3. **Phase-specific agent template**: A template file named ``{agent_name}_{prompt_type}_phase_{phase}.jinja2``
4. **General agent template**: A template file named ``{agent_name}_{prompt_type}.jinja2``
5. **Phase-specific shared template**: A template file named ``all_{prompt_type}_phase_{phase}.jinja2``
6. **General shared template**: A template file named ``all_{prompt_type}.jinja2``
7. **Error fallback**: Raise a ``FileNotFoundError`` if no prompt source is found

Examples:

For an agent named "trader" in phase 2, the system prompt resolution would check:

.. code-block:: text

    1. Is there a registered system prompt handler for phase 2?
    2. Does the agent have a method called get_phase_2_system_prompt?
    3. Does prompts/trader_system_phase_2.jinja2 exist?
    4. Does prompts/trader_system.jinja2 exist?
    5. Does prompts/all_system_phase_2.jinja2 exist?
    6. Does prompts/all_system.jinja2 exist?
    7. Raise error if none found


This approach lets you provide general prompts that work for most phases and override them for specific phases as needed.

Handler Resolution Logic
------------------------

When handling a phase, the Agent class follows a similar resolution process:

1. **Phase Eligibility Check**: First, the agent checks if the phase is in its ``task_phases`` list. If not, the phase is skipped.

2. **Custom Handler Resolution**: If a custom handler is registered for the phase (either through explicit registration or method naming convention), it is used.

3. **Default LLM Handler**: If no custom handler is found, the agent falls back to the default ``handle_phase_with_llm`` method, which:

   a. Gets the system prompt using the prompt resolution logic
   b. Gets the user prompt using the prompt resolution logic
   c. Sends both prompts to the LLM
   d. Parses the response using the response parser resolution logic

This resolution process applies to all four customizable aspects:

* **Phase Handlers**: Determine the overall behavior for a phase
* **System Prompt Handlers**: Generate system prompts for a phase
* **User Prompt Handlers**: Generate user prompts for a phase
* **Response Parsers**: Parse LLM responses for a phase

Each aspect follows the same pattern: check for a registered handler, then fall back to default behavior.
