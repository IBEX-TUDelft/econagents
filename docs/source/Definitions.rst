Definitions
===========

This document defines the main concepts in econagents.

Game Structure
--------------

**Game**
    An economic experiment with players, phases, roles, actions, and state.

**Game Server**
    The external server that owns the authoritative game state and emits
    protocol messages.

**Agent**
    The runtime for one simulated player. It receives events, maintains that
    player's local state, triggers role decisions, and sends actions.

**Game Runner**
    The supervisor for a collection of agents. It starts agents,
    manages logging, enforces timeouts, and stops agents during cleanup.

Domain Concepts
---------------

**Event**
    A decoded server message represented by ``Event(type, data)``.

**Action**
    A role decision before it is encoded for the wire protocol.

**Phase**
    A temporal segment of a game. A phase id can be a string or integer.

**Turn-based Phase**
    A phase where an agent acts once when the phase begins.

**Continuous Phase**
    A phase where an agent acts repeatedly until the phase changes.

**Role**
    A player task definition. In code this is a ``Role`` with a role id,
    name, LLM provider, phase participation settings, prompts, and response
    parsing behavior.

State
-----

**Meta Information**
    Administrative state such as game id, player number, and current phase.

**Private Information**
    State visible to the current player.

**Public Information**
    State visible to all players.

Ports And Adapters
------------------

**Transport Port**
    Async interface for sending and receiving raw messages.

**Message Codec**
    Adapter that translates raw protocol messages into domain events and
    domain actions into outbound protocol messages.

**State Projector**
    Adapter that applies an event to a ``GameState``.

**Prompt Renderer**
    Adapter that renders prompts for a role and phase.

**Response Parser**
    Adapter that validates and converts LLM output into an action payload.
