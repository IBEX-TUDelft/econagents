Customizing Agent Roles
=======================

This guide explains how to customize agent roles in the econagents framework, leveraging the flexible architecture of the ``AgentRole`` class.

.. contents:: Table of Contents
   :depth: 3
   :local:

Agent Role Architecture Overview
--------------------------------

The ``AgentRole`` class is the main class for defining agents and roles (tasks) in an experiment.

At a minimum, you need to specify the following: role id, name, and LLM model.

It also lets you define phases where that role needs to perform an action by either specifying them in the ``task_phases`` attribute or by excluding them in the ``excluded_phases`` attribute.

For handling different phases, the ``AgentRole`` class provides a flexible system that lets you:

1. Define default behavior for all phases
2. Customize handlers for specific phases
3. Customize prompt generators for specific phases
4. Customize response parsers for specific phases

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

There are three main approaches to customize the behavior of your agent for specific phases:

Method 1: Prompt Templates
~~~~~~~~~~~~~~~~~~~~~~~~~~

The default and recommended approach is to define prompt templates in the ``prompts/`` directory (or the directory you specify in the game runner configuration):

.. code-block:: text

    prompts/
    ├── roleName_system.jinja2                # Default system prompt for agents with role roleName
    ├── roleName_system_phase_2.jinja2        # Phase-specific system prompt for agents with role roleName
    ├── roleName_user_phase_6.jinja2          # Phase-specific user prompt for agents with role roleName
    └── all_user_phase_8.jinja2               # Shared prompt for all agents in specific phase

The ``AgentRole`` class will automatically look for these files and use them to generate prompts. By following this naming convention, you can customize the actions of your agent for specific phases.

Prompt Resolution Logic
^^^^^^^^^^^^^^^^^^^^^^^

When generating system or user prompts for a phase, the ``AgentRole`` class follows a specific cascading resolution order. This applies only to prompt generation, not the overall phase handling logic.

For both system and user prompts, the resolution order is:

1. **Registered prompt handler**: A handler registered via ``register_system_prompt_handler`` or ``register_user_prompt_handler``
2. **Phase-specific method**: A method with naming pattern ``get_phase_{phase_number}_system_prompt`` or ``get_phase_{phase_number}_user_prompt``
3. **Phase-specific agent template**: A template file named ``{role_name}_{prompt_type}_phase_{phase}.jinja2``
4. **General agent template**: A template file named ``{role_name}_{prompt_type}.jinja2``
5. **Phase-specific shared template**: A template file named ``all_{prompt_type}_phase_{phase}.jinja2``
6. **General shared template**: A template file named ``all_{prompt_type}.jinja2``
7. **Error fallback**: Raise a ``FileNotFoundError`` if no prompt source is found

Examples:

For an agent with the role "trader" in phase 2, the system prompt resolution would check:

.. code-block:: text

    1. Is there a registered system prompt handler for phase 2?
    2. Does the agent have a method called get_phase_2_system_prompt?
    3. Does prompts/trader_system_phase_2.jinja2 exist?
    4. Does prompts/trader_system.jinja2 exist?
    5. Does prompts/all_system_phase_2.jinja2 exist?
    6. Does prompts/all_system.jinja2 exist?
    7. Raise error if none found


This approach lets you provide general prompts that work for most phases and override them for specific phases as needed.


Method 2: Phase-Specific Methods
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The second approach is to define methods with specific naming patterns in your agent subclass:

.. code-block:: python

    class YourAgent(Agent):
        role = 1
        name = "YourAgent"
        task_phases = [2, 6, 8]
        llm = ChatOpenAI()

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
            """Custom handler for phase 3."""
            # Custom phase handling logic
            return result

The Agent class automatically detects these methods and registers them for the appropriate phases.

Method 3: Explicit Registration
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

Phase Handler Resolution Logic
------------------------

Method 1 will handle phases for you automatically. In methods 2 or 3, you have more control over the phase handling logic.

It's important to understand how the phase handling logic works:

1. **Phase Eligibility Check**:
    - If ``task_phases`` and ``excluded_task_phases`` are not set, the agent will handle all phases.
    - If ``task_phases`` is set, the agent will only handle the phases in the list.
    - If ``excluded_task_phases`` is set, the agent will handle all phases except those in the list.

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

Each aspect follows the same pattern: check for a registered handler, if no registered handler is identified fall back to default behavior.

Note that this is different from the prompt resolution logic, which only applies to prompt generation, not the overall phase handling logic.
