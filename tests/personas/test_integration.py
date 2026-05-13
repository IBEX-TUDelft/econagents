"""End-to-end persona integration with config parser and AgentRole rendering."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import ClassVar

import pytest
import yaml

from econagents.config_parser.base import (
    AgentMappingConfig,
    AgentRoleConfig,
    BaseConfigParser,
    ExperimentConfig,
)
from econagents.core.agent_role import AgentRole
from econagents.core.state.game import GameState
from econagents.llm.openai import ChatOpenAI
from econagents.personas import Persona, load_persona, save_persona


class _MockLLM(ChatOpenAI):
    async def get_response(self, *args, **kwargs):
        return "{}"

    def build_messages(self, *args, **kwargs):
        return []


class _PersonaAwareRole(AgentRole):
    role: ClassVar[int] = 1
    name: ClassVar[str] = "player"
    llm = _MockLLM()


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
    assert rendered.endswith("Some prose.")


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


def test_create_agent_role_attaches_persona():
    cfg = AgentRoleConfig(role_id=1, name="player", llm_params={"model_name": "gpt-test"})
    persona = Persona(id="alice", traits={"cooperativeness": "high"})
    role = cfg.create_agent_role(persona=persona)
    assert role.persona == persona


def test_persona_id_field_on_agent_mapping():
    m = AgentMappingConfig(id=1, role_id=1, persona_id="conditional-cooperator")
    assert m.persona_id == "conditional-cooperator"


def test_inline_persona_on_agent_mapping():
    m = AgentMappingConfig(
        id=1,
        role_id=1,
        persona={"id": "alice-inline", "traits": {"cooperativeness": "high"}},
    )
    assert m.persona is not None
    assert m.persona.id == "alice-inline"
    assert m.persona.traits == {"cooperativeness": "high"}


def test_inline_and_referenced_persona_are_mutually_exclusive():
    with pytest.raises(ValueError, match="not both"):
        AgentMappingConfig(
            id=1,
            role_id=1,
            persona_id="conditional-cooperator",
            persona={"id": "alice-inline"},
        )


def test_inline_persona_resolves_via_run_experiment_path(tmp_path: Path):
    """run_experiment should attach an inline persona without consulting personas_dir."""
    yaml_dir = tmp_path / "experiment"
    yaml_dir.mkdir()
    config_dict = {
        "name": "inline-persona-test",
        "agent_roles": [{"role_id": 1, "name": "player", "llm_params": {"model_name": "gpt-test"}}],
        "agents": [
            {
                "id": 1,
                "role_id": 1,
                "persona": {
                    "id": "alice-inline",
                    "demographics": {"age": 30},
                    "traits": {"cooperativeness": "high"},
                },
            }
        ],
        "state": {
            "meta_information": [{"name": "phase", "type": "int", "default": 0}],
            "private_information": [],
            "public_information": [],
        },
        "manager": {"type": "TurnBasedPhaseManager"},
        "runner": {
            "type": "TurnBasedGameRunner",
            "hostname": "localhost",
            "port": 1,
            "path": "ws",
            "game_id": 1,
        },
    }
    yaml_path = yaml_dir / "config.yaml"
    yaml_path.write_text(yaml.safe_dump(config_dict))

    parser = BaseConfigParser(config_path=yaml_path)
    mapping = parser.config.agents[0]
    assert mapping.persona is not None
    assert mapping.persona.id == "alice-inline"
    assert mapping.persona.traits["cooperativeness"] == "high"
    # personas_dir was never set; inline personas don't need one.
    assert parser.config.personas_dir is None


def test_personas_dir_resolved_relative_to_yaml(tmp_path: Path):
    """personas_dir written relative in YAML must resolve relative to the YAML file."""
    yaml_dir = tmp_path / "experiment"
    yaml_dir.mkdir()
    personas_dir = yaml_dir / "personas"
    save_persona(Persona(id="custom-pal", traits={"cooperativeness": "high"}), personas_dir / "custom-pal.yaml")

    config_dict = {
        "name": "test",
        "personas_dir": "./personas",
        "agent_roles": [{"role_id": 1, "name": "player", "llm_params": {"model_name": "gpt-test"}}],
        "agents": [{"id": 1, "role_id": 1, "persona_id": "custom-pal"}],
        "state": {
            "meta_information": [{"name": "phase", "type": "int", "default": 0}],
            "private_information": [],
            "public_information": [],
        },
        "manager": {"type": "TurnBasedPhaseManager"},
        "runner": {
            "type": "TurnBasedGameRunner",
            "hostname": "localhost",
            "port": 1,
            "path": "ws",
            "game_id": 1,
        },
    }
    yaml_path = yaml_dir / "config.yaml"
    yaml_path.write_text(yaml.safe_dump(config_dict))

    parser = BaseConfigParser(config_path=yaml_path)
    assert parser.config.personas_dir == personas_dir.resolve()

    # Loading via the resolved path should work from any cwd.
    p = load_persona("custom-pal", user_dir=parser.config.personas_dir)
    assert p.traits["cooperativeness"] == "high"


def test_personas_dir_absolute_left_alone(tmp_path: Path):
    abs_dir = tmp_path / "absolute"
    abs_dir.mkdir()
    config = ExperimentConfig.model_validate(
        {
            "name": "test",
            "personas_dir": str(abs_dir),
            "agent_roles": [],
            "agents": [],
            "state": {
                "meta_information": [],
                "private_information": [],
                "public_information": [],
            },
            "manager": {"type": "TurnBasedPhaseManager"},
            "runner": {
                "type": "TurnBasedGameRunner",
                "hostname": "h",
                "port": 1,
                "path": "ws",
                "game_id": 1,
            },
        }
    )
    # Without going through BaseConfigParser, absolute paths are simply preserved.
    assert config.personas_dir == abs_dir
