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

Example usage:

.. code-block:: python

    # Create a basic agent manager
    manager = AgentManager(
        url="wss://game-server.example.com",
        login_payload={"username": "agent1", "password": "secret"},
        game_id=123,
        logger=logging.getLogger("agent"),
    )

    # Start the manager
    await manager.start()

Turn-Based Agent Managers
~~~~~~~~~~~~~~~~~~~~~~~~~

The framework provides specialized managers for turn-based games:

``TurnBasedManager``
^^^^^^^^^^^^^^^^^^^^

This manager extends the base ``AgentManager`` to handle phase-based turn games:

* **Phase Transitions**: Automatically detects and handles phase changes
* **Game State Management**: Updates state (if provided) when events occur
* **Agent Delegation**: Forwards phase changes to the agent for decision-making

Example usage:

.. code-block:: python

    # Create a turn-based manager
    manager = TurnBasedManager(
        url="wss://game-server.example.com",
        login_payload={"username": "agent1", "password": "secret"},
        game_id=123,
        phase_transition_event="phase_change",
        logger=logging.getLogger("agent"),
        state=game_state,
        agent=agent,
    )

    # Register a custom phase handler
    manager.register_phase_handler(2, handle_bidding_phase)

    # Start the manager
    await manager.start()

``TurnBasedWithContinuousManager``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This manager extends ``TurnBasedManager`` to handle games that combine turn-based and continuous action phases:

* **Continuous Phase Support**: Regularly prompts the agent for actions during continuous phases
* **Configurable Action Timing**: Randomized delays between actions to simulate natural behavior
* **Automatic Task Management**: Handles background tasks for continuous phases

Example usage:

.. code-block:: python

    # Create a turn-based manager with continuous phases
    manager = TurnBasedWithContinuousManager(
        url="wss://game-server.example.com",
        login_payload={"username": "agent1", "password": "secret"},
        game_id=123,
        phase_transition_event="phase_change",
        logger=logging.getLogger("agent"),
        continuous_phases={3, 5},  # Phases 3 and 5 are continuous
        min_action_delay=10,       # Minimum 10 seconds between actions
        max_action_delay=20,       # Maximum 20 seconds between actions
        state=game_state,
        agent=agent,
    )

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
