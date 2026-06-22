Personas
========

Personas are a way to give each agent a **stable, portable identity** — demographics, behavioral traits, and an optional prose bio — that gets injected into the system prompt. A single neutral role can drive very different behavior depending on the persona attached to it, which makes personas a clean lever for controlled experiments (factorial demographics, behavioral archetype comparison, ablations).

.. contents:: Table of Contents
   :depth: 3
   :local:

Concept
-------

A persona is a small Pydantic model with four fields:

.. code-block:: python

    class Persona(BaseModel):
        id: str
        demographics: dict[str, Any] = {}
        traits: dict[str, Any] = {}
        bio: str = ""

- ``id`` is a stable unique identifier.
- ``demographics`` and ``traits`` are open ``dict`` types. Trait values should stay machine-readable (``"high"`` / ``"low"`` / numeric).
- ``bio`` is an optional prose paragraph appended below the demographics/traits.

Two entry points, different surfaces
------------------------------------

How you attach a persona depends on which entry point you use:

- **YAML experiments** declare personas in a top-level ``personas:`` list and reference them by id from each agent mapping. All persona content lives in the YAML; there is no file-based or bundled-by-id resolution from this path.
- **Code-driven experiments** call :func:`econagents.personas.load_persona` to resolve a persona by id, with the bundled starter library as a built-in fallback and an optional ``user_dir`` for file-based personas.

Attaching personas via YAML
---------------------------

Declare each persona once in the top-level ``personas:`` list, then reference it by id from any number of agents:

.. code-block:: yaml

    personas:
      - id: "maria-cooperative"
        demographics:
          age: 37
          country: ES
          occupation: social-worker
        traits:
          cooperativeness: high
          reciprocity: high
        bio: You believe most people are trying their best.

      - id: "marcus-strategic"
        demographics:
          age: 44
          country: US
          occupation: hedge-fund-analyst
        traits:
          cooperativeness: low
        bio: You evaluate every situation by expected value.

    agents:
      - id: 1
        role_id: 1
        persona_id: "maria-cooperative"   # multiple agents may share this id
      - id: 2
        role_id: 1
        persona_id: "marcus-strategic"

Persona ids must be unique within the ``personas`` list, and any ``persona_id`` on an agent mapping must resolve to a persona in that list. Both checks fire at config-load time with a clear error message.

If you need to reference a bundled archetype by id, or to load personas from external files, use the code-driven entry point instead — those resolution mechanisms are not available from YAML.

Attaching personas via code
---------------------------

In code-driven experiments, use :func:`econagents.personas.load_persona` and pass the resolved persona to your role's constructor before creating the runtime.

.. code-block:: python

    from econagents.personas import load_persona

    # Bundled archetype — works anywhere
    cooperator = load_persona("conditional-cooperator")

    # User-authored file — picked up automatically from <cwd>/personas/
    custom = load_persona("my-custom")

    role = Prisoner(persona=custom)

The signature is ``load_persona(persona_id, user_dir=None)``. Resolution:

1. If ``user_dir`` is provided, it's used as-is.
2. Otherwise, the loader checks ``<cwd>/personas`` and uses it when that directory exists.
3. If neither yielded a match, the loader falls back to the bundled library, raising :class:`econagents.personas.PersonaNotFoundError` if nothing matches.

The user directory wins on collision, so you can override a bundled persona by dropping a file with the same id into your local ``personas/`` directory. Pass ``user_dir=`` explicitly when you want a different location — for example, scripts that need to run from any working directory:

.. code-block:: python

    from pathlib import Path

    PERSONAS_DIR = Path(__file__).parent / "my-custom-personas"
    custom = load_persona("my-custom", user_dir=PERSONAS_DIR)

Auto-render contract
--------------------

When a persona is attached to a role, the library **automatically appends a standard markdown block** to the system prompt — no template changes required. The block looks like:

.. code-block:: text

    ## About You

    - age: 44
    - country: US
    - occupation: hedge-fund-analyst

    Tendencies:
    - cooperativeness: low

    You evaluate every situation by expected value.

Sections with empty underlying data are omitted, so an archetype-only persona (no demographics, no bio) produces just the ``Tendencies:`` list and nothing else.

This behavior is controlled by ``Role.auto_render_persona`` (default ``True``):

.. code-block:: python

    class MyRole(Role):
        auto_render_persona = False   # take full control via {{ persona }}

When disabled, the rendered system prompt is exactly what your template produces. The persona dict is still injected into the Jinja context as ``{{ persona }}``, so you can format it however you want:

.. code-block:: jinja
    :caption: Custom persona rendering in a Jinja template

    {% if persona %}
    You are a {{ persona.demographics.age }}-year-old
    {{ persona.demographics.occupation }}. {{ persona.bio }}
    {% endif %}

Auto-render is **system-prompt only**. User prompts and phase-specific prompt handlers are not augmented — they're full overrides of the default rendering path.

Authoring custom personas
-------------------------

A persona file is a YAML document with the four fields shown earlier. Filename stem becomes the persona id.

.. code-block:: yaml
    :caption: ./personas/cautious-trader.yaml

    id: cautious-trader
    demographics:
      age: 52
      country: "JP"
      occupation: portfolio-manager
    traits:
      risk_tolerance: low
      patience: high
    bio: |
      You've seen two market crashes in your career. You favor slow,
      compounding gains and treat large drawdowns as catastrophic.

A few authoring tips:

- **Quote ambiguous values** (``country: "NO"``) so YAML doesn't coerce them to booleans.
- **Keep trait values categorical** (``high`` / ``low`` / a number). The auto-render block iterates trait dict keys as a bullet list; long prose values will render awkwardly.
- **Bio is optional** — leave it empty for trait-only or demographics-only personas. The library does this for the bundled archetypes.
- **Ids must be unique** within a personas directory tree (the loader walks recursively).

Bundled starter library
-----------------------

The bundled library at ``econagents/personas/library/`` ships two flat sets of primitives, organized into subdirectories that mirror the taxonomy:

**Behavioral archetypes** (``library/archetypes/``) — empty demographics, populated traits. Recognizable to economists across prisoner / dictator / public goods / ultimatum / trust games:

- ``unconditional-cooperator``, ``conditional-cooperator``, ``free-rider``, ``altruist``, ``spiteful``, ``risk-averse``, ``risk-seeking``, ``inequity-averse``

**Demographic profiles** (``library/demographics/``) — empty traits, populated demographics. Spread across age / country / education / occupation cells:

- ``student-us-21``, ``professional-de-35``, ``retiree-jp-68``, ``parent-br-42``, ``worker-in-29``, ``teacher-no-48``, ``entrepreneur-ke-33``

The loader treats subdirectories as an organizational convenience. From the code-driven path you always reference a bundled persona by its bare id (``load_persona("free-rider")``), never by path. Bundled personas are not reachable from YAML; if you want one in a YAML experiment, copy its fields into the top-level ``personas:`` list (or inline it on an agent).

Public API
----------

.. code-block:: python

    from econagents.personas import (
        Persona,
        PersonaNotFoundError,
        load_persona,
        save_persona,
    )

See the :doc:`api` page for full signatures.

End-to-end examples
-------------------

Two examples in the repository demonstrate the entry-point split:

- ``examples/prisoner_personas/prisoner.yaml`` — YAML-driven, personas declared in the top-level ``personas:`` list and referenced by id from each agent. All in one file.
- ``examples/prisoner_personas/run_game.py`` + ``agents.py`` — code-driven, bundled and file-based personas via ``load_persona`` and agent-runtime factories.

Both reuse the prisoner server from ``examples/prisoner/``, so the only difference between the two examples is *how* personas are attached.
