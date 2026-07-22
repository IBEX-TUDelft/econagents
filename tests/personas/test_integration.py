"""End-to-end persona integration with YAML loading and Role rendering."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import ClassVar

import pytest
import yaml

from econagents.adapters.config import (
    AgentSpec,
    RoleSpec,
    YamlExperimentLoader,
)
from econagents.adapters.parsing import JsonResponseParser
from econagents.adapters.prompts import JinjaPromptRenderer
from econagents.domain.role import PERSONA_INSTRUCTION, Role
from econagents.domain.state.game import GameState
from econagents.adapters.llm.openai import ChatOpenAI
from econagents.personas import Persona


class _MockLLM(ChatOpenAI):
    async def get_response(self, *args, **kwargs):
        return "{}"

    def build_messages(self, *args, **kwargs):
        return []


class _PersonaAwareRole(Role):
    role: ClassVar[int] = 1
    name: ClassVar[str] = "player"
    llm = _MockLLM()
    prompt_renderer = JinjaPromptRenderer()
    response_parser = JsonResponseParser()


class _NoAutoRenderRole(_PersonaAwareRole):
    auto_render_persona = False


class _SimpleState(GameState):
    pass


@pytest.fixture
def prompts_with_persona(tmp_path: Path) -> Path:
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "player_system.jinja2").write_text(
        "country={{ persona.demographics.country }} coop={{ persona.traits.cooperativeness }}"
    )
    (prompts / "player_user.jinja2").write_text("phase={{ meta.phase }}")
    return prompts


def test_persona_renders_in_system_prompt(prompts_with_persona: Path):
    """The persona dict is exposed to Jinja as {{ persona }} regardless of auto-render."""
    persona = Persona(
        id="alice",
        demographics={"country": "US"},
        traits={"cooperativeness": "high"},
    )
    # Disable auto-render so we test the Jinja-context exposure in isolation.
    role = _NoAutoRenderRole(logger=logging.getLogger("t"), persona=persona)
    state = _SimpleState()
    rendered = role.get_phase_system_prompt(state, prompts_path=prompts_with_persona)
    assert rendered == "country=US coop=high"


def test_no_persona_renders_none(tmp_path: Path):
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "player_system.jinja2").write_text("{% if persona %}has{% else %}none{% endif %}")
    (prompts / "player_user.jinja2").write_text("x")
    role = _PersonaAwareRole(logger=logging.getLogger("t"))
    rendered = role.get_phase_system_prompt(_SimpleState(), prompts_path=prompts)
    assert rendered == "none"


@pytest.fixture
def trivial_prompts(tmp_path: Path) -> Path:
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "player_system.jinja2").write_text("base system")
    (prompts / "player_user.jinja2").write_text("base user")
    return prompts


def test_auto_render_appends_standard_block(trivial_prompts: Path):
    persona = Persona(
        id="alice",
        demographics={"age": 30, "country": "US"},
        traits={"cooperativeness": "high"},
        bio="Some prose.",
    )
    role = _PersonaAwareRole(logger=logging.getLogger("t"), persona=persona)
    rendered = role.get_phase_system_prompt(_SimpleState(), prompts_path=trivial_prompts)
    assert rendered.startswith("base system")
    assert "## About You" in rendered
    assert "- age: 30" in rendered
    assert "- country: US" in rendered
    assert "Tendencies:" in rendered
    assert "- cooperativeness: high" in rendered
    assert "Some prose." in rendered
    # The in-character directive closes the block, after the bio.
    assert rendered.index("Some prose.") < rendered.index(PERSONA_INSTRUCTION)
    assert rendered.endswith(PERSONA_INSTRUCTION)


def test_auto_render_off_skips_block(trivial_prompts: Path):
    persona = Persona(id="alice", traits={"cooperativeness": "high"})
    role = _NoAutoRenderRole(logger=logging.getLogger("t"), persona=persona)
    rendered = role.get_phase_system_prompt(_SimpleState(), prompts_path=trivial_prompts)
    assert rendered == "base system"


def test_auto_render_with_no_persona_is_noop(trivial_prompts: Path):
    role = _PersonaAwareRole(logger=logging.getLogger("t"))
    rendered = role.get_phase_system_prompt(_SimpleState(), prompts_path=trivial_prompts)
    assert rendered == "base system"


def test_auto_render_skips_empty_persona(trivial_prompts: Path):
    """A persona with only an id (no demographics/traits/bio) produces an empty block and no append."""
    role = _PersonaAwareRole(logger=logging.getLogger("t"), persona=Persona(id="ghost"))
    rendered = role.get_phase_system_prompt(_SimpleState(), prompts_path=trivial_prompts)
    assert rendered == "base system"


def test_auto_render_does_not_affect_user_prompt(trivial_prompts: Path):
    persona = Persona(id="alice", traits={"cooperativeness": "high"})
    role = _PersonaAwareRole(logger=logging.getLogger("t"), persona=persona)
    rendered_user = role.get_phase_user_prompt(_SimpleState(), prompts_path=trivial_prompts)
    assert rendered_user == "base user"
    assert "Tendencies" not in rendered_user


def test_state_key_named_persona_wins_over_injection(tmp_path: Path):
    """If a state happens to expose a 'persona' key, it must shadow the injection."""
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "player_system.jinja2").write_text("{{ persona }}")
    (prompts / "player_user.jinja2").write_text("x")

    class StateWithPersona(GameState):
        persona: str = "from-state"

    role = _PersonaAwareRole(
        logger=logging.getLogger("t"),
        persona=Persona(id="alice"),
    )
    rendered = role.get_phase_system_prompt(StateWithPersona(), prompts_path=prompts)
    assert rendered == "from-state"


def test_create_role_attaches_persona():
    cfg = RoleSpec(role_id=1, name="player", llm_params={"model_name": "gpt-test"})
    persona = Persona(id="alice", traits={"cooperativeness": "high"})
    role = cfg.create_role(persona=persona)
    assert role.persona == persona


def test_persona_id_on_agent_mapping_is_a_string_ref():
    """persona_id is set as a string; resolution happens at ExperimentSpec level."""
    m = AgentSpec(id=1, role_id=1, persona_id="alice")
    assert m.persona_id == "alice"


def _make_experiment_dict(personas, agents):
    return {
        "name": "test",
        "roles": [{"role_id": 1, "name": "player", "llm_params": {"model_name": "gpt-test"}}],
        "personas": personas,
        "agents": agents,
        "state": {
            "meta_information": [{"name": "phase", "type": "int", "default": 0}],
            "private_information": [],
            "public_information": [],
        },
        "runtime": {"mode": "turn_based"},
        "runner": {
            "type": "TurnBasedGameRunner",
            "hostname": "h",
            "port": 1,
            "path": "ws",
            "game_id": 1,
        },
    }


def test_top_level_personas_resolve_by_id(tmp_path: Path):
    """A persona declared once at the top level can be referenced by multiple agents."""
    config_dict = _make_experiment_dict(
        personas=[
            {"id": "shared", "traits": {"cooperativeness": "high"}},
        ],
        agents=[
            {"id": 1, "role_id": 1, "persona_id": "shared"},
            {"id": 2, "role_id": 1, "persona_id": "shared"},
        ],
    )
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text(yaml.safe_dump(config_dict))

    parser = YamlExperimentLoader(config_path=yaml_path)
    assert len(parser.config.personas) == 1
    assert parser.config.personas[0].id == "shared"
    assert all(a.persona_id == "shared" for a in parser.config.agents)


def test_unknown_persona_id_is_rejected(tmp_path: Path):
    config_dict = _make_experiment_dict(
        personas=[{"id": "known", "traits": {"cooperativeness": "high"}}],
        agents=[{"id": 1, "role_id": 1, "persona_id": "unknown"}],
    )
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text(yaml.safe_dump(config_dict))

    with pytest.raises(ValueError, match="not declared in the top-level"):
        YamlExperimentLoader(config_path=yaml_path)


def test_duplicate_persona_id_is_rejected(tmp_path: Path):
    config_dict = _make_experiment_dict(
        personas=[
            {"id": "dup", "traits": {"cooperativeness": "high"}},
            {"id": "dup", "traits": {"cooperativeness": "low"}},
        ],
        agents=[],
    )
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text(yaml.safe_dump(config_dict))

    with pytest.raises(ValueError, match="Duplicate persona id"):
        YamlExperimentLoader(config_path=yaml_path)
