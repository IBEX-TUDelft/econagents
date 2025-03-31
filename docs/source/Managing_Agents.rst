Agent Managers
==============

Overview
--------

Agent Managers in the econagents framework provide the infrastructure for connecting agents to game servers, handling events, and managing agent lifecycles. This document explains the agent manager architecture and its key components.

Core Components
---------------

Base Agent Manager
~~~~~~~~~~~~~~~~~~

The ``AgentManager`` class serves as the foundation for all agent managers in the system, providing:

* **WebSocket Communication**: Handles connections to game servers
* **Event Handling**: A robust event handling system with hooks and handlers
* **Message Processing**: Parses and routes messages from the server

Key features of the base manager include:

* **Pre and Post Event Hooks**: Custom hooks that run before and after specific events
* **Global Event Handling**: Handlers that process all events regardless of type
* **Event-specific Handlers**: Custom handlers for specific event types

However, you'd rarely need to use the ``AgentManager`` class directly. Instead, you'd use one of the specialized manager classes that inherit from it.

``PhaseManager``
^^^^^^^^^^^^^^^^

This abstract base class provides the foundation for all phase-based managers:

* **Phase Transition Handling**: Core mechanism for handling phase changes
* **Continuous-time Phase Support**: Built-in support for phases requiring periodic actions
* **Flexible Configuration**: Property setters for dynamic configuration
* **State Management**: Automatic game state updates via event hooks

``TurnBasedPhaseManager``
^^^^^^^^^^^^^^^^^^^^^^^^^

This concrete implementation handles turn-based games:

* **Phase Action Execution**: Delegates phase actions to registered handlers or the agent
* **Custom Phase Handlers**: Register specialized handlers for specific phases
* **Agent Integration**: Automatically forwards phase actions to the agent when no handler exists
* **All phases are turn-based**: All phases in this manager are treated as turn-based by default, with actions taken only when explicitly triggered

Example usage:

.. code-block:: python

    # Create a turn-based phase manager
    manager = TurnBasedPhaseManager(
        url="wss://game-server.example.com",
        phase_transition_event="phase_change",
        phase_identifier_key="phase_number",
        auth_mechanism=SimpleLoginPayloadAuth(),
        auth_mechanism_kwargs={
            "login_payload": {"username": "agent1", "password": "secret"},
        },
        state=game_state,
        agent_role=agent,
        logger=logging.getLogger("agent"),
        prompts_dir=Path("prompts"),
    )

    # Register a custom phase handler
    manager.register_phase_handler(2, handle_bidding_phase)

    # Start the manager
    await manager.start()

``HybridPhaseManager``
^^^^^^^^^^^^^^^^^^^^^^

This manager handles games that combine turn-based and continuous action phases:

* **Continuous-time Phase Configuration**: By default, all phases are treated as turn-based unless explicitly specified in the ``continuous_phases`` parameter
* **Configurable Action Timing**: Control the frequency of actions in continuous-time phases
* **Shared Implementation**: Leverages the same phase action execution mechanism as TurnBasedPhaseManager

Example usage:

.. code-block:: python

    # Create a hybrid phase manager
    manager = HybridPhaseManager(
        url="wss://game-server.example.com",
        phase_transition_event="phase_change",
        phase_identifier_key="phase_number",
        continuous_phases={3, 5},  # Phases 3 and 5 are continuous
        min_action_delay=10,       # Minimum 10 seconds between actions
        max_action_delay=20,       # Maximum 20 seconds between actions
        auth_mechanism=SimpleLoginPayloadAuth(),
        auth_mechanism_kwargs={
            "login_payload": {"username": "agent1", "password": "secret"},
        },
        state=game_state,
        agent_role=agent,
        logger=logging.getLogger("agent"),
        prompts_dir=Path("prompts"),
    )

    # Register a custom phase handler
    manager.register_phase_handler(2, handle_bidding_phase)

    # Start the manager
    await manager.start()

Event Handling Architecture
---------------------------

The event handling system follows this sequence for each event:

1. **Global Pre-Event Hooks**: Run for all events first
2. **Event-Specific Pre-Event Hooks**: Run for specific event types
3. **Global Event Handlers**: Process all events
4. **Event-Specific Handlers**: Process specific event types
5. **Event-Specific Post-Event Hooks**: Run after specific event handlers
6. **Global Post-Event Hooks**: Run after all event processing

This architecture allows for a flexible event handling system that can be customized for specific needs.

Phase Transition Process
------------------------

When using phase-based managers, phase transitions follow this sequence:

1. **Phase Transition Event**: Server sends an event indicating a phase change
2. **Current Phase Shutdown**: If in a continuous-time phase, any pending phase actions are cancelled
3. **Phase Update**: The current phase is updated to the new phase
4. **Phase Type Determination**:
   * For turn-based phases (default): An initial action is executed once
   * For continuous-time phases (if specified in ``continuous_phases``): A background task is started that will repeatedly execute actions with random delays between ``min_action_delay`` and ``max_action_delay``
5. **Initial Action**: An initial action is executed for the new phase

This systematic approach ensures smooth transitions between different types of game phases. To designate specific phases as continuous, use the ``HybridPhaseManager`` and specify them in the ``continuous_phases`` parameter. By default, all phases are treated as turn-based.
