"""Focused tests for lifecycle-oriented CLI command handlers."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_cmd_install_with_hooks_calls_install_and_install_hooks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from attocode.code_intel.cli import _cmd_install

    observed: dict[str, object] = {}

    monkeypatch.setattr(
        "attocode.code_intel.installer.install",
        lambda target, project_dir=".", scope="local": observed.setdefault(
            "install",
            (target, project_dir, scope),
        ) or True,
    )
    monkeypatch.setattr(
        "attocode.code_intel.installer.install_hooks",
        lambda target, project_dir=".": observed.setdefault("hooks", (target, project_dir)),
    )

    _cmd_install(["cursor", "--project", "/tmp/demo", "--global", "--hooks"])

    assert observed["install"] == ("cursor", "/tmp/demo", "user")
    assert observed["hooks"] == ("cursor", "/tmp/demo")


def test_cmd_install_missing_target_exits() -> None:
    from attocode.code_intel.cli import _cmd_install

    with pytest.raises(SystemExit) as exc_info:
        _cmd_install([])

    assert exc_info.value.code == 1


def test_cmd_uninstall_calls_hooks_and_uninstall(monkeypatch: pytest.MonkeyPatch) -> None:
    from attocode.code_intel.cli import _cmd_uninstall

    observed: dict[str, object] = {}

    monkeypatch.setattr(
        "attocode.code_intel.installer.uninstall_hooks",
        lambda target, project_dir=".": observed.setdefault("hooks", (target, project_dir)),
    )
    monkeypatch.setattr(
        "attocode.code_intel.installer.uninstall",
        lambda target, project_dir=".", scope="local": observed.setdefault(
            "uninstall",
            (target, project_dir, scope),
        ) or True,
    )

    _cmd_uninstall(["cursor", "--project", "/tmp/demo", "--global"])

    assert observed["hooks"] == ("cursor", "/tmp/demo")
    assert observed["uninstall"] == ("cursor", "/tmp/demo", "user")


def test_cmd_uninstall_missing_target_exits() -> None:
    from attocode.code_intel.cli import _cmd_uninstall

    with pytest.raises(SystemExit) as exc_info:
        _cmd_uninstall([])

    assert exc_info.value.code == 1


def test_cmd_probe_install_missing_target_exits() -> None:
    from attocode.code_intel.cli import _cmd_probe_install

    with pytest.raises(SystemExit) as exc_info:
        _cmd_probe_install([])

    assert exc_info.value.code == 1


def test_cmd_bundle_help(capsys: pytest.CaptureFixture[str]) -> None:
    from attocode.code_intel.cli import _cmd_bundle

    _cmd_bundle(["--help"])
    captured = capsys.readouterr()

    assert "attocode code-intel bundle export" in captured.out
    assert "attocode code-intel bundle inspect" in captured.out


def test_cmd_bundle_unknown_subcommand_exits() -> None:
    from attocode.code_intel.cli import _cmd_bundle

    with pytest.raises(SystemExit) as exc_info:
        _cmd_bundle(["explode"])

    assert exc_info.value.code == 1


def test_cmd_bundle_export_uses_default_output_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from attocode.code_intel.cli import _cmd_bundle

    observed: dict[str, object] = {}

    def _fake_export(project_dir: str, output_path: str) -> Path:
        observed["project_dir"] = project_dir
        observed["output_path"] = output_path
        return Path(output_path)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("attocode.code_intel.bundle.export_bundle", _fake_export)

    _cmd_bundle(["export", "--project", str(tmp_path / "repo")])
    captured = capsys.readouterr()

    assert observed["project_dir"] == str(tmp_path / "repo")
    assert observed["output_path"] == str(tmp_path / "attocode-bundle-repo.tar.gz")
    assert "Bundle exported to" in captured.out


def test_cmd_status_reports_installed_targets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from attocode.code_intel.cli import _cmd_status

    (tmp_path / ".cursor").mkdir()
    (tmp_path / ".cursor" / "mcp.json").write_text(
        '{"mcpServers": {"attocode-code-intel": {"command": "x"}}}',
        encoding="utf-8",
    )
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "config.toml").write_text(
        '[mcp_servers.attocode-code-intel]\ncommand = "x"\nargs = []\n',
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("shutil.which", lambda tool: "/usr/bin/claude" if tool == "claude" else None)
    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: type("Result", (), {"stdout": "attocode-code-intel\n"})(),
    )
    monkeypatch.setattr("attocode.code_intel.installer._get_user_config_dir", lambda _app: None)
    monkeypatch.setattr("attocode.code_intel.installer._find_command", lambda _project_dir=None: "attocode-code-intel")

    _cmd_status()
    captured = capsys.readouterr()

    assert "Claude Code: installed" in captured.out
    assert "Cursor: installed" in captured.out
    assert "Codex: installed" in captured.out
    assert "Entry point: attocode-code-intel (on PATH)" in captured.out
