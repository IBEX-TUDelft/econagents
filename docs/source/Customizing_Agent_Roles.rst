Customizing Agent Roles
=======================

This guide explains how to customize agent roles in the econagents framework, leveraging the flexible architecture of the ``AgentRole`` class.

.. contents:: Table of Contents
   :depth: 3
   :local:

Agent Role Architecture Overview
--------------------------------

The ``AgentRole`` class is your main entry point for defining agents and roles (tasks) in an experiment. **At a minimum**, you need to specify:

- **Role ID**
- **Agent name**
- **LLM model**

You can also control in which phases the agent will act by listing them in the ``task_phases`` attribute (or excluding them via ``excluded_phases``).

When a phase begins, the agent checks:

1. **Phase eligibility** (based on the above lists).
2. **Which handlers or prompts** to use for that phase.

The system is designed so that you can provide both general default behaviors and more targeted, phase-specific custom logic.

How Phase Handling Works (High-Level Flow)
------------------------------------------

The handler is how the agent decides *what to do* in a phase, while the prompt is how the agent decides *what to say* when it calls the LLM. Here's the high-level flow:

1. **Check Phase Eligibility**
   If a phase is in the agent's ``task_phases`` (or not in ``excluded_phases``), the agent will attempt to handle it.

2. **Resolve a Phase Handler**
   The agent looks for a **custom handler** for that phase (either via explicitly registered handlers or naming conventions). If one is found, it executes that handler.
   - If **no custom handler** is found, it falls back to the **default LLM-based handler** (``handle_phase_with_llm``).

3. **(Default Handler Only) Prompt Resolution**
   If using the default LLM handler, the agent automatically generates a **system prompt** and a **user prompt** for that phase. These prompts are resolved according to the **prompt resolution logic** described below (either from files, methods, or handlers).

4. **Send Prompts to LLM**
   The default handler then calls the LLM with the resolved prompts.

5. **Response Parsing**
   The agent uses the **response parser resolution** to process the LLM output (either via explicit registration, naming convention, or a default parser).

6. **Return Phase Result**
   The custom or default handler returns the final result for that phase.

Phase-Specific Customization Points
-----------------------------------

When you decide to customize the agent's behavior for specific phases, you can change up to four components:

1. **System Prompt** – a role-defining, scenario-framing prompt.
2. **User Prompt** – instructions or context for the specific phase.
3. **Response Parser** – logic to interpret the LLM's response.
4. **Phase Handler** – overarching logic for that phase (which may not even call the LLM).

You can customize these components by combining any of the following three approaches:

1. **Prompt Templates** (Method 1)
2. **Phase-Specific Methods** (Method 2)
3. **Explicit Registration** (Method 3)

The sections below describe each approach in detail, followed by deeper dives into prompt resolution and handler resolution logic.

Customization Approaches
------------------------

Method 1: Prompt Templates
~~~~~~~~~~~~~~~~~~~~~~~~~~

The **default and recommended** approach is to define prompt templates in the ``prompts/`` directory (or whichever directory is specified in your game runner configuration):

.. code-block:: text

    prompts/
    ├── your_agent_system.jinja2                # Default system prompt
    ├── your_agent_system_phase_2.jinja2        # Phase-specific system prompt
    ├── your_agent_user_phase_6.jinja2          # Phase-specific user prompt
    └── all_user_phase_8.jinja2                 # Shared prompt for all agents

The ``AgentRole`` class automatically discovers these templates and uses them to generate prompts according to a strict **naming convention** (explained in "Prompt Resolution Logic" below).

Using Partials for Reusability
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

To promote reusability and maintain consistency across your prompts, you can leverage Jinja's `include` tag to insert common snippets. For example, you might create a partial template containing standard game information:

.. code-block:: text
    :caption: prompts/_partials/_game_information.jinja2

    1. **Game Information**:
       - Phase: {{ meta.phase }}
       - Your Role: {{ meta.role }} (Player #{{ meta.player_number }})
       - Name: {{ meta.player_name }}

You can then include this partial in your main prompt templates:

.. code-block:: jinja
    :caption: Example user prompt using include

    {% include "_partials/_game_information.jinja2" %}

    **Your Decision Options**:
    ... rest of the prompt ...

This approach helps keep your prompts organized and DRY (Don't Repeat Yourself), making maintenance easier. The `AgentRole`'s prompt rendering mechanism supports standard Jinja features, including includes.

**Note:** Prompt templates *only* control what text is sent to the LLM. If you want to customize the overall phase logic (e.g., do multiple calls to the LLM or skip the LLM entirely), you need to register or define a **custom handler** (see below).

Method 2: Phase-Specific Methods
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Another way to customize prompts, parsers, or even the entire phase logic is by adding methods that follow a **phase-based naming pattern** in your agent subclass:

.. code-block:: python

    class YourAgent(Agent):
        role = 1
        name = "YourAgent"
        task_phases = [2, 6, 8]
        llm = ChatOpenAI()

        # -- Custom system/user prompts --
        def get_phase_2_system_prompt(self, state):
            return "You are an economic agent in phase 2..."

        def get_phase_6_user_prompt(self, state):
            return "Current market state: ..."

        # -- Custom response parser --
        def parse_phase_8_llm_response(self, response, state):
            # parse the response
            return parsed_data

        # -- Custom phase handler --
        def handle_phase_3(self, phase, state):
            # bypass the LLM entirely if you want
            return {"custom": "logic for phase 3"}

Any method that matches these naming conventions is automatically detected and used in place of the default behavior. For example, if you define ``handle_phase_3(...)``, the agent will use that method to handle phase 3 instead of the default LLM approach.

Method 3: Explicit Registration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Finally, you can manually register handlers in your agent's ``__init__`` method:

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
            return {"parsed": "data"}

        async def custom_phase_handler(self, phase, state):
            # entire custom logic for phase 2
            return {"result": "from custom phase handler"}

Either approach—naming conventions or explicit registration—lets you override the default prompts, parsers, or phase handling.

Prompt Resolution Logic
-----------------------

**Prompt resolution** applies only when the agent uses the **default LLM handler** (i.e., no custom phase handler is overriding the process). When the default LLM handler runs, it needs to generate:

1. A **system prompt**
2. A **user prompt**

To do this, it follows a **cascading resolution order** for each prompt type (system vs. user). Below is the resolution order for system prompts, with user prompts following the same pattern:

1. **Registered prompt handler**
   A handler registered via ``register_system_prompt_handler`` (or ``register_user_prompt_handler``).

2. **Phase-specific method**
   A method with a matching pattern:
   - ``get_phase_{phase_number}_system_prompt(...)``
   - ``get_phase_{phase_number}_user_prompt(...)``

3. **Phase-specific agent template**
   A file named ``{agent_name}_system_phase_{phase}.jinja2`` (or ``{agent_name}_user_phase_{phase}.jinja2``).

4. **General agent template**
   A file named ``{agent_name}_system.jinja2`` (or ``{agent_name}_user.jinja2``).

5. **Phase-specific shared template**
   A file named ``all_system_phase_{phase}.jinja2`` (or ``all_user_phase_{phase}.jinja2``).

6. **General shared template**
   A file named ``all_system.jinja2`` (or ``all_user.jinja2``).

7. **Error Fallback**
   If none of the above exist, a ``FileNotFoundError`` is raised.

Example (System Prompt, Phase 2)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

For an agent named "trader" handling **phase 2**, the agent checks for a system prompt in this order:

.. code-block:: text

    1. Registered system prompt handler for phase 2?
    2. get_phase_2_system_prompt(...) method?
    3. prompts/trader_system_phase_2.jinja2 ?
    4. prompts/trader_system.jinja2 ?
    5. prompts/all_system_phase_2.jinja2 ?
    6. prompts/all_system.jinja2 ?
    7. FileNotFoundError if none are found.

This mechanism ensures you can define broad, reusable prompts while still allowing tailored prompts for specific phases.

Handler Resolution Logic
------------------------

**Handler resolution** determines the *overall logic* used to handle a given phase. It is independent from (but often used alongside) prompt resolution.

1. **Phase Eligibility Check**
   - If neither ``task_phases`` nor ``excluded_task_phases`` is set, the agent attempts to handle *all* phases.
   - If ``task_phases`` is set, only those listed phases are handled.
   - If ``excluded_task_phases`` is set, all phases *except* those in the list are handled.

2. **Custom Handler Resolution**
   If a **custom phase handler** is registered (via ``register_phase_handler``) or detected by method naming convention (e.g., ``handle_phase_3``), the agent uses that handler.

3. **Default LLM Handler**
   If no custom handler is found, the agent uses the default implementation:
   1. **Prompt Resolution** (for system/user prompts)
   2. **Call the LLM**
   3. **Response Parsing** (using parser resolution)
   4. Return the final result.

Comparing Prompt vs. Handler Resolution
---------------------------------------

- **Prompt Resolution**: Determines *what text the agent sends to the LLM* (system + user prompts).
- **Handler Resolution**: Determines *how the phase is handled overall*. This can include calls to the LLM (and hence prompt resolution) or skip the LLM entirely.

If you only need to change the *prompts* for a phase, you can rely on **prompt resolution**. If you need to change the *entire logic* for a phase (e.g., skipping the LLM, performing additional calculations), you must define or register a **custom handler**.
