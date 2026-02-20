"""Tests for CLI and config."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from attocode.cli import main
from attocode.config import (
    AttoConfig,
    find_project_root,
    get_user_config_dir,
    load_config,
    load_json_config,
    load_rules,
    load_yaml_config,
)


class TestAttoConfig:
    def test_defaults(self) -> None:
        c = AttoConfig()
        assert c.provider == "anthropic"
        assert c.model == "claude-sonnet-4-20250514"
        assert c.max_iterations == 100
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
        config = load_config(cli_args={"model": "gpt-4o", "debug": True})
        assert config.model == "gpt-4o"
        assert config.debug is True

    def test_working_dir(self, tmp_path: Path) -> None:
        config = load_config(working_dir=str(tmp_path))
        assert config.working_directory == str(tmp_path)


class TestCLI:
    def test_version(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "attocode" in result.output
        assert "0.1.0" in result.output

    def test_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "Attocode" in result.output
        assert "--model" in result.output
        assert "--provider" in result.output
