Overview
========

econagents runs LLM agents in economic experiments. The game server remains
the source of truth; econagents connects simulated players to that server,
projects server events into each player's local state, asks the player's role
for an action, and sends that action back through the configured protocol.

.. contents:: Table of Contents
   :depth: 3
   :local:

Architecture
------------

The runtime is organized around explicit boundaries:

* **Domain types** describe stable concepts such as ``Event``, ``Action``,
  ``PhaseId``, and ``AgentContext``.
* **Ports** define interfaces for protocol codecs, transports, prompt
  renderers, response parsers, and state projectors.
* **Adapters** implement those ports for concrete systems such as IBEX JSON
  envelopes, WebSockets, Jinja prompt files, and ``EventField`` state mapping.
* **Runtime services** compose those pieces. ``Agent`` runs one
  simulated player, ``PhaseEngine`` controls turn-based and continuous phases,
  and ``GameRunner`` supervises a set of agents.

The default protocol adapter is ``IbexMessageCodec``. It expects messages in
this envelope:

.. code-block:: json

   {"meta": {"type": "phase-started"}, "payload": {"phase": "decision"}}

``meta.type`` becomes the internal event type and ``payload`` becomes event
data. Outbound actions are encoded with the same codec before they are sent
through the transport.

Runtime Flow
------------

For each simulated player, an ``Agent`` performs this sequence:

1. Receive a raw message from the transport.
2. Decode it into an ``Event`` with the configured ``MessageCodec``.
3. Project the event into the player's ``GameState``.
4. If the event changes phase, ask ``PhaseEngine`` whether to act once or run a
   continuous action loop.
5. Ask the ``Role`` for an action when the role participates in that phase.
6. Encode the action and send it through the transport.

Roles
-----------

A ``Role`` defines what a player does. It specifies:

* ``role``: numeric role id
* ``name``: prompt/template role name
* ``llm``: provider used for decisions
* ``task_phases`` or ``task_phases_excluded``: phases where the role acts
* optional response schemas for structured model output

Example:

.. code-block:: python

   from typing import Literal
   from pydantic import BaseModel
   from econagents import Role
   from econagents.adapters.llm import ChatOpenAI

   class Choice(BaseModel):
       meta: dict
       payload: dict[str, Literal["COOPERATE", "DEFECT"]]

   class Prisoner(Role):
       role = 1
       name = "Prisoner"
       llm = ChatOpenAI(model_name="gpt-4o-mini")
       task_phases = ["decision"]
       default_response_schema = Choice

``Agent`` supplies Jinja prompt rendering and ``JsonResponseParser`` by
default. You can inject another prompt renderer or response parser on the role
when a game needs a different decision pipeline.

Game State
----------

Each runtime owns a ``GameState`` with three sections:

* ``meta``: game id, phase, player number, and administrative context
* ``private_information``: state visible to the current player
* ``public_information``: state visible to all players

Fields declared with ``EventField`` are updated by ``EventFieldStateProjector``
when incoming event data contains the matching key.

.. code-block:: python

   from pydantic import Field
   from econagents import EventField, GameState, MetaInformation, PrivateInformation, PublicInformation

   class Meta(MetaInformation):
       phase: str | int = EventField(default=0)

   class PrivateInfo(PrivateInformation):
       total_score: int = EventField(default=0)

   class PublicInfo(PublicInformation):
       history: list[dict] = EventField(default_factory=list)

   class MyState(GameState):
       meta: Meta = Field(default_factory=Meta)
       private_information: PrivateInfo = Field(default_factory=PrivateInfo)
       public_information: PublicInfo = Field(default_factory=PublicInfo)

Running A Game
--------------

Code-driven experiments build agents explicitly and pass them to
``GameRunner``:

.. code-block:: python

   from pathlib import Path
   from econagents import GameRunner, TurnBasedGameRunnerConfig
   from examples.prisoner.agents import create_prisoner_agents

   config = TurnBasedGameRunnerConfig(
       game_id=1,
       hostname="localhost",
       port=8765,
       path="",
       prompts_dir=Path("prompts"),
       max_game_duration=300,
   )

   agents = create_prisoner_agents(config, recovery_codes)
   runner = GameRunner(config=config, agents=agents)
   await runner.run_game()

YAML-driven experiments use ``runtime`` settings to create the same runtime
objects from configuration:

.. code-block:: yaml

   runtime:
     mode: turn_based

   runner:
     type: TurnBasedGameRunner
     hostname: localhost
     port: 8765
     path: ""
     phase_transition_event: phase-transition
     phase_identifier_key: phase
