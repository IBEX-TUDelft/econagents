"""Unit tests for the persona module."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from econagents.personas import (
    BUILTIN_LIBRARY,
    Persona,
    PersonaNotFoundError,
    load_persona,
    save_persona,
)


class TestPersonaModel:
    def test_minimal_persona(self):
        p = Persona(id="alice")
        assert p.id == "alice"
        assert p.demographics == {}
        assert p.traits == {}
        assert p.bio == ""

    def test_full_persona(self):
        p = Persona(
            id="alice",
            demographics={"age": 30, "country": "US"},
            traits={"cooperativeness": "high"},
            bio="Some prose.",
        )
        assert p.demographics["age"] == 30
        assert p.traits["cooperativeness"] == "high"
        assert p.bio == "Some prose."

    def test_frozen(self):
        p = Persona(id="alice")
        with pytest.raises(ValidationError):
            p.id = "bob"  # type: ignore[misc]

    def test_extra_keys_forbidden(self):
        with pytest.raises(ValidationError):
            Persona(id="alice", typo_field="oops")  # type: ignore[call-arg]


class TestLoadPersona:
    def test_loads_from_user_dir(self, tmp_path: Path):
        path = tmp_path / "alice.yaml"
        path.write_text("id: alice\ntraits: {cooperativeness: high}\n")
        p = load_persona("alice", user_dir=tmp_path)
        assert p.id == "alice"
        assert p.traits == {"cooperativeness": "high"}

    def test_falls_back_to_builtin(self, tmp_path: Path):
        # The bundled library ships free-rider; user_dir doesn't.
        p = load_persona("free-rider", user_dir=tmp_path)
        assert p.id == "free-rider"
        assert p.traits["cooperativeness"] == "low"

    def test_falls_back_with_no_user_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        # Chdir to a tmp dir so the cwd default has nothing to find — must fall back to bundled.
        monkeypatch.chdir(tmp_path)
        p = load_persona("conditional-cooperator")
        assert p.id == "conditional-cooperator"

    def test_user_dir_overrides_builtin(self, tmp_path: Path):
        # User-authored persona shadows the bundled one with the same id.
        path = tmp_path / "free-rider.yaml"
        path.write_text("id: free-rider\ntraits: {cooperativeness: medium}\n")
        p = load_persona("free-rider", user_dir=tmp_path)
        assert p.traits["cooperativeness"] == "medium"

    def test_missing_in_both_raises(self, tmp_path: Path):
        with pytest.raises(PersonaNotFoundError) as exc:
            load_persona("does-not-exist", user_dir=tmp_path)
        assert exc.value.persona_id == "does-not-exist"

    def test_missing_with_no_user_dir_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(PersonaNotFoundError):
            load_persona("does-not-exist")

    def test_defaults_to_cwd_personas_when_user_dir_unset(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Without user_dir, the loader checks <cwd>/personas as a sensible default."""
        cwd_personas = tmp_path / "personas"
        cwd_personas.mkdir()
        (cwd_personas / "neighborhood-pal.yaml").write_text("id: neighborhood-pal\ntraits: {cooperativeness: high}\n")
        monkeypatch.chdir(tmp_path)
        p = load_persona("neighborhood-pal")
        assert p.id == "neighborhood-pal"
        assert p.traits == {"cooperativeness": "high"}

    def test_cwd_default_does_not_apply_when_no_personas_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """If <cwd>/personas doesn't exist, the default silently falls through to bundled."""
        monkeypatch.chdir(tmp_path)
        # 'free-rider' is bundled; tmp_path has no personas/ dir, so bundled is the only source.
        p = load_persona("free-rider")
        assert p.id == "free-rider"

    def test_typo_in_yaml_raises(self, tmp_path: Path):
        path = tmp_path / "alice.yaml"
        path.write_text("id: alice\nunknown_field: oops\n")
        with pytest.raises(ValidationError):
            load_persona("alice", user_dir=tmp_path)


class TestSavePersona:
    def test_round_trip(self, tmp_path: Path):
        original = Persona(
            id="alice",
            demographics={"age": 30, "country": "US"},
            traits={"cooperativeness": "high"},
        )
        path = tmp_path / "alice.yaml"
        save_persona(original, path)
        reloaded = load_persona("alice", user_dir=tmp_path)
        assert reloaded == original

    def test_creates_parent_dirs(self, tmp_path: Path):
        path = tmp_path / "nested" / "dir" / "alice.yaml"
        save_persona(Persona(id="alice"), path)
        assert path.exists()

    def test_writes_sorted_keys(self, tmp_path: Path):
        path = tmp_path / "alice.yaml"
        save_persona(
            Persona(id="alice", traits={"z": 1, "a": 2}, demographics={"country": "US"}),
            path,
        )
        text = path.read_text()
        # Top-level keys should be sorted: bio, demographics, id, traits.
        assert text.index("bio:") < text.index("demographics:") < text.index("id:") < text.index("traits:")


class TestBuiltinLibrary:
    def test_library_dir_exists(self):
        assert BUILTIN_LIBRARY.is_dir()

    def test_expected_subdirectories(self):
        assert (BUILTIN_LIBRARY / "archetypes").is_dir()
        assert (BUILTIN_LIBRARY / "demographics").is_dir()

    def test_every_bundled_yaml_loads_and_id_matches_filename(self):
        files = sorted(BUILTIN_LIBRARY.rglob("*.yaml"))
        assert len(files) >= 10, "Bundled library should ship a meaningful starter set"
        for path in files:
            data = yaml.safe_load(path.read_text())
            persona = Persona.model_validate(data)
            assert persona.id == path.stem, f"id mismatch in {path.name}"

    def test_bundled_ids_are_unique(self):
        stems = [p.stem for p in BUILTIN_LIBRARY.rglob("*.yaml")]
        assert len(stems) == len(set(stems)), "Bundled persona ids must be unique across subdirectories"

    def test_country_no_is_string_not_bool(self):
        # Quoted "NO" must round-trip as a string, not get coerced to False.
        p = load_persona("teacher-no-48")
        assert p.demographics["country"] == "NO"

    def test_loader_finds_persona_in_archetype_subdir(self):
        # Caller doesn't know about subdirectories — id alone is enough.
        p = load_persona("free-rider")
        assert p.id == "free-rider"

    def test_loader_finds_persona_in_demographic_subdir(self):
        p = load_persona("student-us-21")
        assert p.id == "student-us-21"
