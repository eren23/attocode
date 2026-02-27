"""Tests for skill state persistence."""

from __future__ import annotations

import json
from pathlib import Path

from attocode.integrations.skills.state import SkillStateStore


class TestInit:
    def test_init_no_dir_creates_in_memory_store(self) -> None:
        store = SkillStateStore()
        assert store._session_dir is None
        # Should work for get/set without disk
        store.set("s", "k", "v")
        assert store.get("s", "k") == "v"

    def test_init_with_dir(self, tmp_path: Path) -> None:
        store = SkillStateStore(session_dir=tmp_path)
        assert store._session_dir == tmp_path

    def test_init_with_string_dir(self, tmp_path: Path) -> None:
        store = SkillStateStore(session_dir=str(tmp_path))
        assert store._session_dir == tmp_path

    def test_init_loads_existing_state(self, tmp_path: Path) -> None:
        """State files on disk should be loaded during init."""
        state_dir = tmp_path / "skill_state"
        state_dir.mkdir()
        (state_dir / "my-skill.json").write_text(
            json.dumps({"counter": 42, "name": "test"}), encoding="utf-8"
        )
        store = SkillStateStore(session_dir=tmp_path)
        assert store.get("my-skill", "counter") == 42
        assert store.get("my-skill", "name") == "test"

    def test_init_ignores_invalid_json(self, tmp_path: Path) -> None:
        state_dir = tmp_path / "skill_state"
        state_dir.mkdir()
        (state_dir / "bad.json").write_text("not-json!!!", encoding="utf-8")
        # Should not raise
        store = SkillStateStore(session_dir=tmp_path)
        assert store.get("bad", "anything") is None

    def test_init_ignores_non_dict_json(self, tmp_path: Path) -> None:
        """JSON files containing non-dict data (e.g. a list) should be skipped."""
        state_dir = tmp_path / "skill_state"
        state_dir.mkdir()
        (state_dir / "listdata.json").write_text("[1,2,3]", encoding="utf-8")
        store = SkillStateStore(session_dir=tmp_path)
        assert store.get("listdata", "anything") is None

    def test_init_no_state_dir_on_disk(self, tmp_path: Path) -> None:
        """If skill_state/ subdir doesn't exist, init still works (empty state)."""
        store = SkillStateStore(session_dir=tmp_path)
        assert store.get("foo", "bar") is None


class TestGetSetDelete:
    def test_set_and_get(self) -> None:
        store = SkillStateStore()
        store.set("skill-a", "key1", "value1")
        assert store.get("skill-a", "key1") == "value1"

    def test_get_missing_key_returns_default(self) -> None:
        store = SkillStateStore()
        assert store.get("skill-a", "missing") is None

    def test_get_missing_key_returns_custom_default(self) -> None:
        store = SkillStateStore()
        assert store.get("skill-a", "missing", default=42) == 42

    def test_get_missing_skill_returns_default(self) -> None:
        store = SkillStateStore()
        assert store.get("nonexistent", "key", default="fallback") == "fallback"

    def test_set_overwrites_existing(self) -> None:
        store = SkillStateStore()
        store.set("s", "k", "old")
        store.set("s", "k", "new")
        assert store.get("s", "k") == "new"

    def test_set_different_types(self) -> None:
        store = SkillStateStore()
        store.set("s", "int_val", 42)
        store.set("s", "float_val", 3.14)
        store.set("s", "bool_val", True)
        store.set("s", "list_val", [1, 2, 3])
        store.set("s", "dict_val", {"nested": "data"})
        store.set("s", "none_val", None)
        assert store.get("s", "int_val") == 42
        assert store.get("s", "float_val") == 3.14
        assert store.get("s", "bool_val") is True
        assert store.get("s", "list_val") == [1, 2, 3]
        assert store.get("s", "dict_val") == {"nested": "data"}
        assert store.get("s", "none_val") is None

    def test_delete_existing_key(self) -> None:
        store = SkillStateStore()
        store.set("s", "k", "v")
        result = store.delete("s", "k")
        assert result is True
        assert store.get("s", "k") is None

    def test_delete_nonexistent_key(self) -> None:
        store = SkillStateStore()
        store.set("s", "other", "v")
        result = store.delete("s", "missing")
        assert result is False

    def test_delete_nonexistent_skill(self) -> None:
        store = SkillStateStore()
        result = store.delete("nonexistent", "key")
        assert result is False

    def test_set_marks_dirty(self) -> None:
        store = SkillStateStore()
        assert store._dirty is False
        store.set("s", "k", "v")
        assert store._dirty is True

    def test_delete_marks_dirty(self) -> None:
        store = SkillStateStore()
        store.set("s", "k", "v")
        store._dirty = False
        store.delete("s", "k")
        assert store._dirty is True

    def test_delete_nonexistent_does_not_mark_dirty(self) -> None:
        store = SkillStateStore()
        store.delete("s", "k")
        assert store._dirty is False


class TestGetAll:
    def test_get_all_returns_copy(self) -> None:
        store = SkillStateStore()
        store.set("s", "a", 1)
        store.set("s", "b", 2)
        result = store.get_all("s")
        assert result == {"a": 1, "b": 2}
        # Verify it's a copy (mutation should not affect store)
        result["c"] = 3
        assert store.get("s", "c") is None

    def test_get_all_empty_skill(self) -> None:
        store = SkillStateStore()
        assert store.get_all("nonexistent") == {}

    def test_get_all_after_delete(self) -> None:
        store = SkillStateStore()
        store.set("s", "a", 1)
        store.set("s", "b", 2)
        store.delete("s", "a")
        assert store.get_all("s") == {"b": 2}


class TestClear:
    def test_clear_one_skill(self) -> None:
        store = SkillStateStore()
        store.set("skill-a", "k1", "v1")
        store.set("skill-a", "k2", "v2")
        store.set("skill-b", "k1", "v1")
        store.clear("skill-a")
        assert store.get_all("skill-a") == {}
        assert store.get("skill-b", "k1") == "v1"

    def test_clear_nonexistent_skill(self) -> None:
        store = SkillStateStore()
        # Should not raise
        store.clear("nonexistent")
        assert store._dirty is False

    def test_clear_marks_dirty(self) -> None:
        store = SkillStateStore()
        store.set("s", "k", "v")
        store._dirty = False
        store.clear("s")
        assert store._dirty is True

    def test_clear_all(self) -> None:
        store = SkillStateStore()
        store.set("skill-a", "k", "v")
        store.set("skill-b", "k", "v")
        store.clear_all()
        assert store.get_all("skill-a") == {}
        assert store.get_all("skill-b") == {}

    def test_clear_all_marks_dirty(self) -> None:
        store = SkillStateStore()
        store.clear_all()
        assert store._dirty is True


class TestPersistence:
    def test_save_creates_files(self, tmp_path: Path) -> None:
        store = SkillStateStore(session_dir=tmp_path)
        store.set("my-skill", "counter", 10)
        store.set("my-skill", "name", "test")
        store.save()

        state_file = tmp_path / "skill_state" / "my-skill.json"
        assert state_file.exists()
        data = json.loads(state_file.read_text(encoding="utf-8"))
        assert data == {"counter": 10, "name": "test"}

    def test_save_then_load(self, tmp_path: Path) -> None:
        """Full roundtrip: save state then load it in a new store."""
        store1 = SkillStateStore(session_dir=tmp_path)
        store1.set("alpha", "x", 100)
        store1.set("alpha", "y", "hello")
        store1.set("beta", "flag", True)
        store1.save()

        store2 = SkillStateStore(session_dir=tmp_path)
        assert store2.get("alpha", "x") == 100
        assert store2.get("alpha", "y") == "hello"
        assert store2.get("beta", "flag") is True

    def test_save_skips_when_not_dirty(self, tmp_path: Path) -> None:
        store = SkillStateStore(session_dir=tmp_path)
        store.set("s", "k", "v")
        store.save()
        # Modify file on disk to detect if save overwrites it
        state_file = tmp_path / "skill_state" / "s.json"
        state_file.write_text('{"tampered": true}', encoding="utf-8")
        # save() should be a no-op since not dirty
        store.save()
        data = json.loads(state_file.read_text(encoding="utf-8"))
        assert data == {"tampered": True}

    def test_save_clears_dirty_flag(self, tmp_path: Path) -> None:
        store = SkillStateStore(session_dir=tmp_path)
        store.set("s", "k", "v")
        assert store._dirty is True
        store.save()
        assert store._dirty is False

    def test_save_without_session_dir_is_noop(self) -> None:
        store = SkillStateStore()
        store.set("s", "k", "v")
        store.save()  # Should not raise
        assert store._dirty is True  # Still dirty since nothing was written

    def test_save_creates_directories(self, tmp_path: Path) -> None:
        session_dir = tmp_path / "nested" / "path"
        # Note: SkillStateStore does not create session_dir itself,
        # but save() creates skill_state/ subdir. The session_dir must exist.
        session_dir.mkdir(parents=True)
        store = SkillStateStore(session_dir=session_dir)
        store.set("s", "k", "v")
        store.save()
        assert (session_dir / "skill_state" / "s.json").exists()

    def test_save_skips_empty_skill_state(self, tmp_path: Path) -> None:
        """Skills with empty state dicts should not produce files."""
        store = SkillStateStore(session_dir=tmp_path)
        store.set("s", "k", "v")
        store.clear("s")
        store.save()
        state_dir = tmp_path / "skill_state"
        if state_dir.exists():
            files = list(state_dir.glob("*.json"))
            assert len(files) == 0

    def test_save_multiple_skills(self, tmp_path: Path) -> None:
        store = SkillStateStore(session_dir=tmp_path)
        store.set("alpha", "a", 1)
        store.set("beta", "b", 2)
        store.set("gamma", "c", 3)
        store.save()

        files = sorted(
            (tmp_path / "skill_state").glob("*.json"),
            key=lambda f: f.name,
        )
        assert [f.stem for f in files] == ["alpha", "beta", "gamma"]

    def test_load_multiple_skills_from_disk(self, tmp_path: Path) -> None:
        state_dir = tmp_path / "skill_state"
        state_dir.mkdir()
        (state_dir / "s1.json").write_text(
            json.dumps({"a": 1}), encoding="utf-8"
        )
        (state_dir / "s2.json").write_text(
            json.dumps({"b": 2}), encoding="utf-8"
        )
        store = SkillStateStore(session_dir=tmp_path)
        assert store.get("s1", "a") == 1
        assert store.get("s2", "b") == 2


class TestMultipleSkillsIndependentState:
    def test_skills_have_independent_state(self) -> None:
        store = SkillStateStore()
        store.set("skill-a", "counter", 1)
        store.set("skill-b", "counter", 100)
        assert store.get("skill-a", "counter") == 1
        assert store.get("skill-b", "counter") == 100

    def test_clear_one_does_not_affect_other(self) -> None:
        store = SkillStateStore()
        store.set("skill-a", "x", 10)
        store.set("skill-b", "y", 20)
        store.clear("skill-a")
        assert store.get("skill-a", "x") is None
        assert store.get("skill-b", "y") == 20

    def test_delete_key_in_one_does_not_affect_other(self) -> None:
        store = SkillStateStore()
        store.set("skill-a", "shared-key", "a-value")
        store.set("skill-b", "shared-key", "b-value")
        store.delete("skill-a", "shared-key")
        assert store.get("skill-a", "shared-key") is None
        assert store.get("skill-b", "shared-key") == "b-value"

    def test_roundtrip_multiple_skills(self, tmp_path: Path) -> None:
        store1 = SkillStateStore(session_dir=tmp_path)
        store1.set("a", "k", 1)
        store1.set("b", "k", 2)
        store1.set("c", "k", 3)
        store1.save()

        store2 = SkillStateStore(session_dir=tmp_path)
        assert store2.get("a", "k") == 1
        assert store2.get("b", "k") == 2
        assert store2.get("c", "k") == 3
