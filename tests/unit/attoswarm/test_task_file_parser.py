"""Tests for task_file_parser module — YAML and Markdown parsing + validation."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from attoswarm.coordinator.task_file_parser import (
    _load_markdown,
    _load_yaml,
    load_tasks_file,
    validate_tasks,
)


# ── YAML parsing ─────────────────────────────────────────────────────


class TestLoadYaml:
    def test_valid(self, tmp_path: Path) -> None:
        f = tmp_path / "tasks.yaml"
        f.write_text(textwrap.dedent("""\
            tasks:
              - task_id: task-1
                title: Build API
                description: Implement REST endpoints
                task_kind: implement
                target_files: [src/server.ts]
              - task_id: task-2
                title: Add tests
                description: Write unit tests
                deps: [task-1]
                task_kind: test
                target_files: [tests/server.test.ts]
        """))
        result = _load_yaml(f)
        assert len(result) == 2
        assert result[0]["task_id"] == "task-1"
        assert result[1]["deps"] == ["task-1"]

    def test_missing_tasks_key(self, tmp_path: Path) -> None:
        f = tmp_path / "tasks.yaml"
        f.write_text("foo: bar\n")
        with pytest.raises(ValueError, match="top-level 'tasks' key"):
            _load_yaml(f)

    def test_tasks_not_list(self, tmp_path: Path) -> None:
        f = tmp_path / "tasks.yaml"
        f.write_text("tasks: not-a-list\n")
        with pytest.raises(ValueError, match="must be a list"):
            _load_yaml(f)


# ── Markdown parsing ─────────────────────────────────────────────────


class TestLoadMarkdown:
    def test_valid(self, tmp_path: Path) -> None:
        f = tmp_path / "tasks.md"
        f.write_text(textwrap.dedent("""\
            ## task-1: Build API server
            Kind: implement
            Role: impl
            Target files: src/server.ts, src/routes.ts

            Implement REST endpoints with validation.

            ## task-2: Add tests
            Kind: test
            Depends on: task-1
            Target files: tests/server.test.ts

            Write unit and integration tests.
        """))
        result = _load_markdown(f)
        assert len(result) == 2
        assert result[0]["task_id"] == "task-1"
        assert result[0]["title"] == "Build API server"
        assert result[0]["task_kind"] == "implement"
        assert result[0]["role_hint"] == "impl"
        assert result[0]["target_files"] == ["src/server.ts", "src/routes.ts"]
        assert "REST endpoints" in result[0]["description"]
        assert result[1]["deps"] == ["task-1"]

    def test_multiline_description(self, tmp_path: Path) -> None:
        f = tmp_path / "tasks.md"
        f.write_text(textwrap.dedent("""\
            ## task-1: Multi-line task
            Kind: implement

            Line one.
            Line two.
            Line three.
        """))
        result = _load_markdown(f)
        assert len(result) == 1
        assert "Line one." in result[0]["description"]
        assert "Line three." in result[0]["description"]

    def test_no_metadata(self, tmp_path: Path) -> None:
        f = tmp_path / "tasks.md"
        f.write_text(textwrap.dedent("""\
            ## task-1: Simple task

            Just a description.
        """))
        result = _load_markdown(f)
        assert len(result) == 1
        assert result[0]["task_id"] == "task-1"


# ── Validation ───────────────────────────────────────────────────────


class TestValidateTasks:
    def test_valid(self) -> None:
        tasks = [
            {"task_id": "t1", "task_kind": "implement"},
            {"task_id": "t2", "task_kind": "test", "deps": ["t1"]},
        ]
        assert validate_tasks(tasks) == []

    def test_empty(self) -> None:
        errors = validate_tasks([])
        assert any("No tasks" in e for e in errors)

    def test_duplicate_ids(self) -> None:
        tasks = [
            {"task_id": "t1", "task_kind": "implement"},
            {"task_id": "t1", "task_kind": "test"},
        ]
        errors = validate_tasks(tasks)
        assert any("Duplicate" in e for e in errors)

    def test_missing_task_id(self) -> None:
        tasks = [{"task_kind": "implement"}]
        errors = validate_tasks(tasks)
        assert any("missing" in e for e in errors)

    def test_unknown_dep(self) -> None:
        tasks = [
            {"task_id": "t1", "task_kind": "implement", "deps": ["t999"]},
        ]
        errors = validate_tasks(tasks)
        assert any("unknown task" in e for e in errors)

    def test_unknown_kind(self) -> None:
        tasks = [{"task_id": "t1", "task_kind": "bogus"}]
        errors = validate_tasks(tasks)
        assert any("unknown task_kind" in e for e in errors)

    def test_circular_deps(self) -> None:
        tasks = [
            {"task_id": "a", "task_kind": "implement", "deps": ["b"]},
            {"task_id": "b", "task_kind": "implement", "deps": ["a"]},
        ]
        errors = validate_tasks(tasks)
        assert any("Circular" in e for e in errors)


# ── load_tasks_file integration ──────────────────────────────────────


class TestLoadTasksFile:
    def test_yaml(self, tmp_path: Path) -> None:
        f = tmp_path / "tasks.yaml"
        f.write_text(textwrap.dedent("""\
            tasks:
              - task_id: t1
                title: Task one
                description: Do stuff
                task_kind: implement
        """))
        specs = load_tasks_file(f)
        assert len(specs) == 1
        assert specs[0].task_id == "t1"
        assert specs[0].title == "Task one"

    def test_markdown(self, tmp_path: Path) -> None:
        f = tmp_path / "tasks.md"
        f.write_text(textwrap.dedent("""\
            ## t1: Task one
            Kind: implement

            Do stuff.
        """))
        specs = load_tasks_file(f)
        assert len(specs) == 1
        assert specs[0].task_id == "t1"

    def test_unsupported_extension(self, tmp_path: Path) -> None:
        f = tmp_path / "tasks.txt"
        f.write_text("nope")
        with pytest.raises(ValueError, match="Unsupported"):
            load_tasks_file(f)

    def test_validation_error_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "tasks.yaml"
        f.write_text(textwrap.dedent("""\
            tasks:
              - task_id: t1
                task_kind: implement
                deps: [t999]
        """))
        with pytest.raises(ValueError, match="unknown task"):
            load_tasks_file(f)
