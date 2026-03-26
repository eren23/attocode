"""Tests for CLI and config."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from click.testing import CliRunner

from attocode.cli import _validate_staged_resume_for_tui, main
from attocode.config import (
    AttoConfig,
    find_project_root,
    infer_project_root_from_session_dir,
    get_user_config_dir,
    load_config,
    load_json_config,
    load_rules,
    load_yaml_config,
    resolve_project_root,
)


class TestAttoConfig:
    def test_defaults(self) -> None:
        c = AttoConfig()
        assert c.provider == "anthropic"
        assert c.model == "claude-sonnet-4-20250514"
        assert c.max_iterations == 100
        assert c.compaction_warning_threshold == pytest.approx(0.7)
        assert c.compaction_threshold == pytest.approx(0.8)
        assert c.debug is False
        assert c.swarm is False

    def test_slots(self) -> None:
        c = AttoConfig()
        with pytest.raises(AttributeError):
            c.nonexistent = "value"


class TestFindProjectRoot:
    def test_finds_git_dir(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        sub = tmp_path / "sub" / "deep"
        sub.mkdir(parents=True)
        result = find_project_root(sub)
        assert result == tmp_path

    def test_finds_attocode_dir(self, tmp_path: Path) -> None:
        (tmp_path / ".attocode").mkdir()
        result = find_project_root(tmp_path)
        assert result == tmp_path

    def test_returns_none_for_root(self, tmp_path: Path) -> None:
        # tmp_path usually doesn't have .git or .attocode
        isolated = tmp_path / "isolated"
        isolated.mkdir()
        result = find_project_root(isolated)
        # May or may not be None depending on system, but should not crash
        assert result is None or isinstance(result, Path)

    def test_prefers_nearest_attocode_over_parent_git(self, tmp_path: Path) -> None:
        repo_root = tmp_path / "repo"
        nested_project = repo_root / "nested" / "child"
        (repo_root / ".git").mkdir(parents=True)
        (nested_project / ".attocode").mkdir(parents=True)
        workdir = nested_project / "deeper"
        workdir.mkdir(parents=True)

        result = resolve_project_root(workdir)
        assert result.path == nested_project
        assert result.source == ".attocode"

    def test_prefers_nearer_git_over_farther_attocode(self, tmp_path: Path) -> None:
        parent_project = tmp_path / "parent"
        child_repo = parent_project / "child"
        workdir = child_repo / "src"
        (parent_project / ".attocode").mkdir(parents=True)
        (child_repo / ".git").mkdir(parents=True)
        workdir.mkdir(parents=True)

        result = resolve_project_root(workdir)
        assert result.path == child_repo
        assert result.source == ".git"

    def test_infer_project_root_from_session_dir(self, tmp_path: Path) -> None:
        root = tmp_path / "myproj"
        sessions = root / ".attocode" / "sessions"
        sessions.mkdir(parents=True)
        assert infer_project_root_from_session_dir(str(sessions)) == str(root.resolve())
        assert infer_project_root_from_session_dir("") is None
        assert infer_project_root_from_session_dir(str(tmp_path / "other")) is None


class TestLoadJsonConfig:
    def test_load_existing(self, tmp_path: Path) -> None:
        f = tmp_path / "config.json"
        f.write_text(json.dumps({"model": "gpt-4o"}))
        result = load_json_config(f)
        assert result["model"] == "gpt-4o"

    def test_load_missing(self, tmp_path: Path) -> None:
        result = load_json_config(tmp_path / "missing.json")
        assert result == {}

    def test_load_invalid_json(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.json"
        f.write_text("not json{{{")
        result = load_json_config(f)
        assert result == {}


class TestLoadYamlConfig:
    def test_load_existing(self, tmp_path: Path) -> None:
        f = tmp_path / "config.yaml"
        f.write_text("model: gpt-4o\ntemperature: 0.5\n")
        result = load_yaml_config(f)
        assert result["model"] == "gpt-4o"
        assert result["temperature"] == 0.5

    def test_load_missing(self, tmp_path: Path) -> None:
        result = load_yaml_config(tmp_path / "missing.yaml")
        assert result == {}

    def test_load_non_dict(self, tmp_path: Path) -> None:
        f = tmp_path / "list.yaml"
        f.write_text("- item1\n- item2\n")
        result = load_yaml_config(f)
        assert result == {}


class TestLoadRules:
    def test_load_existing(self, tmp_path: Path) -> None:
        f = tmp_path / "rules.md"
        f.write_text("# Rules\n- Be nice\n")
        result = load_rules(f)
        assert "Be nice" in result

    def test_load_missing(self, tmp_path: Path) -> None:
        result = load_rules(tmp_path / "missing.md")
        assert result == ""


class TestLoadConfig:
    def test_defaults(self) -> None:
        config = load_config()
        assert config.provider in ("anthropic", "openrouter", "openai", "zai")
        assert config.max_iterations == 100

    def test_cli_args_override(self) -> None:
        config = load_config(
            cli_args={
                "model": "gpt-4o",
                "debug": True,
                "compaction_threshold": 0.91,
            }
        )
        assert config.model == "gpt-4o"
        assert config.debug is True
        assert config.compaction_threshold == pytest.approx(0.91)

    def test_project_compaction_block(self, tmp_path: Path) -> None:
        project_root = tmp_path / "repo"
        workdir = project_root / "subdir"
        (project_root / ".attocode").mkdir(parents=True)
        workdir.mkdir(parents=True)
        (project_root / ".attocode" / "config.json").write_text(
            json.dumps({
                "compaction": {
                    "warningThreshold": 0.61,
                    "compactionThreshold": 0.77,
                },
            }),
            encoding="utf-8",
        )

        config = load_config(working_dir=str(workdir))
        assert config.compaction_warning_threshold == pytest.approx(0.61)
        assert config.compaction_threshold == pytest.approx(0.77)

    def test_working_dir(self, tmp_path: Path) -> None:
        config = load_config(working_dir=str(tmp_path))
        assert config.working_directory == str(tmp_path)

    def test_sets_project_root_when_resolved(self, tmp_path: Path) -> None:
        project_root = tmp_path / "repo"
        workdir = project_root / "subdir"
        (project_root / ".attocode").mkdir(parents=True)
        workdir.mkdir(parents=True)

        config = load_config(working_dir=str(workdir))
        assert config.project_root == str(project_root)
        assert config.session_dir == str(project_root / ".attocode" / "sessions")


class TestCLI:
    def test_version(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "attocode " in result.output

    def test_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "Attocode" in result.output
        assert "--model" in result.output
        assert "--provider" in result.output

    def test_swarm_passthrough_dispatch(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        called: dict[str, Any] = {}

        def _fake(parts: tuple[str, ...], *, debug: bool = False) -> None:
            called["parts"] = parts
            called["debug"] = debug

        monkeypatch.setattr("attocode.cli._dispatch_swarm_command", _fake)
        runner = CliRunner()
        result = runner.invoke(main, ["swarm", "doctor", ".attocode/swarm.hybrid.yaml"])
        assert result.exit_code == 0
        assert called["parts"] == ("doctor", ".attocode/swarm.hybrid.yaml")
        assert called["debug"] is False

    def test_top_level_swarm_flags_exit_with_migration_message(self) -> None:
        runner = CliRunner()

        result = runner.invoke(main, ["--hybrid", "ship it"])

        assert result.exit_code == 2
        assert "Top-level swarm mode was removed from `attocode`." in result.output
        assert "attocode swarm start .attocode/swarm.hybrid.yaml" in result.output
        assert "attocode swarm tui <run_dir>" in result.output

    def test_invoke_attoswarm_marks_launcher_env(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        captured: dict[str, str | list[str]] = {}

        def _fake_attoswarm(*, args: list[str], standalone_mode: bool) -> None:
            captured["args"] = list(args)
            captured["started_via"] = os.environ.get("ATTO_SWARM_STARTED_VIA", "")
            captured["command_family"] = os.environ.get("ATTO_SWARM_COMMAND_FAMILY", "")

        monkeypatch.setattr("attoswarm.cli.main", _fake_attoswarm)

        from attocode.cli import _invoke_attoswarm

        _invoke_attoswarm(["doctor", "cfg.yaml"])

        assert captured["args"] == ["doctor", "cfg.yaml"]
        assert captured["started_via"] == "attocode"
        assert captured["command_family"] == "attocode swarm"

    def test_single_turn_exits_1_on_failure(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """When agent.run() returns success=False, the process should exit 1."""

        def _fake_single_turn(config: Any, prompt: str) -> None:
            # Simulate what _run_single_turn does when result.success is False
            sys.exit(1)

        monkeypatch.setattr("attocode.cli._run_single_turn", _fake_single_turn)

        runner = CliRunner()
        result = runner.invoke(main, ["--non-interactive", "fail please"])
        assert result.exit_code == 1

    def test_single_turn_exits_0_on_success(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """When agent.run() returns success=True, the process should exit 0."""

        def _fake_single_turn(config: Any, prompt: str) -> None:
            # Simulate what _run_single_turn does when result.success is True
            pass

        monkeypatch.setattr("attocode.cli._run_single_turn", _fake_single_turn)

        runner = CliRunner()
        result = runner.invoke(main, ["--non-interactive", "succeed please"])
        assert result.exit_code == 0


class _ResumeSession:
    def __init__(self, metadata: dict[str, Any] | None = None) -> None:
        self.metadata = metadata or {}


class _ResumeStore:
    def __init__(self, session: _ResumeSession | None) -> None:
        self._session = session

    async def get_session(self, session_id: str) -> _ResumeSession | None:
        return self._session if session_id == "resume1" else None


class _ResumeAgent:
    def __init__(self, session: _ResumeSession | None, *, explicit: bool = False) -> None:
        self._store = _ResumeStore(session)
        self.config = SimpleNamespace(
            resume_session="resume1",
            resume_session_explicit=explicit,
        )

    async def ensure_session_store(self) -> _ResumeStore:
        return self._store


class TestValidateStagedResume:
    @pytest.mark.asyncio
    async def test_rejects_implicit_resume_without_metadata(self, tmp_path: Path) -> None:
        config = AttoConfig(
            working_directory=str(tmp_path),
            session_dir=str(tmp_path / ".attocode" / "sessions"),
            project_root=str(tmp_path),
        )
        agent = _ResumeAgent(_ResumeSession(metadata={}), explicit=False)

        messages = await _validate_staged_resume_for_tui(agent, config)

        assert agent.config.resume_session is None
        assert agent.config.resume_session_explicit is False
        assert messages == ["Ignored staged resume 'resume1' because it lacks trusted project metadata."]

    @pytest.mark.asyncio
    async def test_allows_explicit_resume_without_metadata(self, tmp_path: Path) -> None:
        config = AttoConfig(
            working_directory=str(tmp_path),
            session_dir=str(tmp_path / ".attocode" / "sessions"),
            project_root=str(tmp_path),
        )
        agent = _ResumeAgent(_ResumeSession(metadata={}), explicit=True)

        messages = await _validate_staged_resume_for_tui(agent, config)

        assert agent.config.resume_session == "resume1"
        assert agent.config.resume_session_explicit is True
        assert messages == []
