Definitions
===========

This document provides formal definitions for the key components, terminology, and architecture of the econagents framework.

.. contents:: Table of Contents
   :depth: 3
   :local:


Game Structure
--------------

**Game**
    An economic experiment that consists of a set of players following a game description. A game consists of a set of phases and a set of roles assigned to players, and a set of information available to players per state of world. A game has at least one phase and one role.

**Game Server**
    The server that hosts the game and manages the game state, player interactions, and experiment logic.

**Middleware**
    The infrastructure that connects LLM agents and the game server, including:

    * **econagents library**: Connects LLM agents and the game server based on experimenter settings
    * **GUI (TBD)**: Provides an interface for experimenters to configure experiments

Naming and Organization
-----------------------

**Phase**
    A distinct temporal segment of a game during which specific actions are available to players. Phases follow each other sequentially in time. Two primary types exist:

    * **Turn-based Phase**: Discrete phases where agents take actions in turns or at specific moments. **By default, all phases are assumed to be turn-based.**
    * **Continuous-time Phase**: Phases where agents can act continuously within time constraints. To designate specific phases as continuous, use the ``HybridPhaseManager`` and specify the continuous-time phases via the ``continuous_phases`` parameter.

**Role**
    A set of tasks specified per phase of the game that defines player capabilities. Several players can have the same role. Roles encapsulate:

    * The agent's identity and responsibilities
    * Available actions in each phase
    * Specialized knowledge or capabilities

**Task/Action**
    The specific choices available to players of a particular role in a phase. Tasks may be:

    * **Empty**: Some roles may have no tasks in certain phases
    * **Numerical Input**: Values (possibly from a restricted range)
    * **Choice Selection**: Selection from a pre-specified list of options
    * **Free Text**: Open-ended text input (where applicable)

**Information Management**
    Data available to players that can influence their choices:

    * **Public Information**: Visible to all players and included in all prompts
    * **Private Information**: Available only to specific players or roles
    * **Meta Information**: Information about the game, such as the rules, the current phase, the current round, etc.

Agent Manager Hierarchy
-----------------------

The econagents system uses a hierarchical approach to agent management:

**Base Agent Manager**
    The foundation class providing core functionality for:

    * WebSocket communication with game servers
    * Event handling and routing
    * Message processing

**Phase Manager**
    Abstract class extending the base manager with phase-specific capabilities:

    * Phase transition handling
    * State management for game phases
    * Lifecycle hooks for phase events

**Specialized Managers**

* **TurnBasedPhaseManager**: Implements logic for turn-based games
* **HybridPhaseManager**: Handles games with both turn-based and continuous-time phases
* **Custom Game Managers**: Game-specific implementations (e.g., PDManager for Prisoner's Dilemma)

Game Runner
-----------

The GameRunner is the main class that connects the game server to the LLM agents. It uses the AgentManager to manage the websocket connections with the game server and the isolated connections with the individual LLMs.

Prompt Structure
----------------

Prompts follow standard templates with role-specific and phase-specific variations. They allow users to include public, private, and meta information appropriately. We use system and user prompts as the main building blocks of prompts.

**System Prompt**
    The foundational instruction set that defines the agent's role, capabilities, and constraints.

    * Establishes the agent's persona and behavioral framework
    * Includes core rules, constraints, and objectives for the agent
    * Remains relatively constant across phases (with possible extensions per phase)
    * Contains game rules, role descriptions, and strategy guidelines
    * Often includes meta-instructions about response formatting and reasoning approaches

**User Prompt**
    The dynamic, context-specific instructions delivered to the agent in each interaction.

    * Contains the current game state and relevant information for decision-making
    * Incorporates both public and private information appropriate to the agent's role
    * Includes specific action options with required formatting (often JSON)
    * Generally updated with each phase and game state change
