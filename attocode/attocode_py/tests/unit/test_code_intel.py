"""Tests for attocode.code_intel — MCP server, installer, CLI dispatch."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Server tool handlers
# ---------------------------------------------------------------------------


class TestServerTools:
    """Test MCP tool handler functions (mocked ASTService)."""

    @pytest.fixture(autouse=True)
    def _setup_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Set up project dir and reset singletons."""
        monkeypatch.setenv("ATTOCODE_PROJECT_DIR", str(tmp_path))

        import attocode.code_intel.server as srv

        srv._ast_service = None
        srv._context_mgr = None
        srv._code_analyzer = None
        yield
        srv._ast_service = None
        srv._context_mgr = None
        srv._code_analyzer = None

    def _make_mock_ast_service(self):
        from attocode.integrations.context.cross_references import SymbolLocation, SymbolRef

        svc = MagicMock()
        svc.initialized = True
        svc._ast_cache = {"a.py": object()}

        svc.get_file_symbols.return_value = [
            SymbolLocation(
                name="foo",
                qualified_name="foo",
                kind="function",
                file_path="a.py",
                start_line=1,
                end_line=10,
            ),
        ]

        svc.find_symbol.return_value = [
            SymbolLocation(
                name="MyClass",
                qualified_name="MyClass",
                kind="class",
                file_path="b.py",
                start_line=5,
                end_line=50,
            ),
        ]

        svc.get_callers.return_value = [
            SymbolRef(
                symbol_name="MyClass",
                ref_kind="call",
                file_path="c.py",
                line=20,
            ),
        ]

        svc.get_dependencies.return_value = {"dep1.py", "dep2.py"}
        svc.get_dependents.return_value = {"user1.py"}
        svc.get_impact.return_value = {"affected1.py", "affected2.py"}
        svc._to_rel.side_effect = lambda p: p

        return svc

    def test_symbols_tool(self):
        import attocode.code_intel.server as srv
        from attocode.code_intel.server import symbols

        srv._ast_service = self._make_mock_ast_service()

        result = symbols("a.py")
        assert "foo" in result
        assert "function" in result
        assert "L1-10" in result

    def test_symbols_not_found(self):
        import attocode.code_intel.server as srv
        from attocode.code_intel.server import symbols

        svc = self._make_mock_ast_service()
        svc.get_file_symbols.return_value = []
        srv._ast_service = svc

        result = symbols("empty.py")
        assert "No symbols found" in result

    def test_search_symbols_tool(self):
        import attocode.code_intel.server as srv
        from attocode.code_intel.server import search_symbols

        srv._ast_service = self._make_mock_ast_service()

        result = search_symbols("MyClass")
        assert "MyClass" in result
        assert "class" in result
        assert "b.py" in result

    def test_dependencies_tool(self):
        import attocode.code_intel.server as srv
        from attocode.code_intel.server import dependencies

        srv._ast_service = self._make_mock_ast_service()

        result = dependencies("a.py")
        assert "dep1.py" in result
        assert "dep2.py" in result
        assert "user1.py" in result
        assert "Imports from" in result
        assert "Imported by" in result

    def test_impact_analysis_tool(self):
        import attocode.code_intel.server as srv
        from attocode.code_intel.server import impact_analysis

        srv._ast_service = self._make_mock_ast_service()

        result = impact_analysis(["a.py"])
        assert "affected1.py" in result
        assert "affected2.py" in result
        assert "2 files affected" in result

    def test_impact_analysis_no_impact(self):
        import attocode.code_intel.server as srv
        from attocode.code_intel.server import impact_analysis

        svc = self._make_mock_ast_service()
        svc.get_impact.return_value = set()
        srv._ast_service = svc

        result = impact_analysis(["isolated.py"])
        assert "No other files are impacted" in result

    def test_cross_references_tool(self):
        import attocode.code_intel.server as srv
        from attocode.code_intel.server import cross_references

        srv._ast_service = self._make_mock_ast_service()

        result = cross_references("MyClass")
        assert "Definitions" in result
        assert "References" in result
        assert "class" in result
        assert "[call]" in result
        assert "c.py:20" in result

    def test_dependency_graph_tool(self):
        import attocode.code_intel.server as srv
        from attocode.code_intel.server import dependency_graph

        srv._ast_service = self._make_mock_ast_service()

        result = dependency_graph("a.py", depth=1)
        assert "Imports (forward)" in result
        assert "Imported by (reverse)" in result

    def test_file_analysis_tool(self, tmp_path: Path):
        import attocode.code_intel.server as srv
        from attocode.code_intel.server import file_analysis
        from attocode.integrations.context.code_analyzer import CodeChunk, FileAnalysis

        analyzer = MagicMock()
        analyzer.analyze_file.return_value = FileAnalysis(
            path=str(tmp_path / "test.py"),
            language="python",
            chunks=[
                CodeChunk(
                    name="greet",
                    kind="function",
                    start_line=1,
                    end_line=5,
                    content="def greet(): pass",
                    signature="def greet()",
                ),
            ],
            imports=["os", "sys"],
            exports=["greet"],
            line_count=10,
        )
        srv._code_analyzer = analyzer

        result = file_analysis(str(tmp_path / "test.py"))
        assert "python" in result
        assert "greet" in result
        assert "function" in result
        assert "os" in result

    def test_repo_map_tool(self):
        import attocode.code_intel.server as srv
        from attocode.code_intel.server import repo_map
        from attocode.integrations.context.codebase_context import RepoMap

        ctx = MagicMock()
        ctx.get_repo_map.return_value = RepoMap(
            tree="src/\n  main.py\n  utils.py",
            files=[],
            total_files=2,
            total_lines=100,
            languages={"python": 2},
        )
        srv._context_mgr = ctx

        result = repo_map(include_symbols=False, max_tokens=4000)
        assert "main.py" in result
        assert "2 files" in result


# ---------------------------------------------------------------------------
# Installer
# ---------------------------------------------------------------------------


class TestInstaller:
    def test_build_server_entry(self, monkeypatch: pytest.MonkeyPatch):
        from attocode.code_intel.installer import _build_server_entry

        # Ensure attocode-code-intel is not on PATH for deterministic test
        monkeypatch.setattr("shutil.which", lambda x: None)

        entry = _build_server_entry("/tmp/project")
        assert entry["command"] is not None
        assert "--project" in entry["args"]
        assert "/tmp/project" in entry["args"]

    def test_install_json_cursor(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from attocode.code_intel.installer import install_json_config

        monkeypatch.setattr("shutil.which", lambda x: None)

        result = install_json_config("cursor", project_dir=str(tmp_path))
        assert result is True

        config_path = tmp_path / ".cursor" / "mcp.json"
        assert config_path.exists()

        data = json.loads(config_path.read_text())
        assert "attocode-code-intel" in data["mcpServers"]
        server = data["mcpServers"]["attocode-code-intel"]
        assert "--project" in server["args"]

    def test_install_json_windsurf(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from attocode.code_intel.installer import install_json_config

        monkeypatch.setattr("shutil.which", lambda x: None)

        result = install_json_config("windsurf", project_dir=str(tmp_path))
        assert result is True

        config_path = tmp_path / ".windsurf" / "mcp.json"
        assert config_path.exists()

    def test_install_json_merges_existing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from attocode.code_intel.installer import install_json_config

        monkeypatch.setattr("shutil.which", lambda x: None)

        # Pre-existing config
        cursor_dir = tmp_path / ".cursor"
        cursor_dir.mkdir()
        existing = {"mcpServers": {"other-server": {"command": "other"}}}
        (cursor_dir / "mcp.json").write_text(json.dumps(existing))

        install_json_config("cursor", project_dir=str(tmp_path))

        data = json.loads((cursor_dir / "mcp.json").read_text())
        assert "other-server" in data["mcpServers"]
        assert "attocode-code-intel" in data["mcpServers"]

    def test_uninstall_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from attocode.code_intel.installer import install_json_config, uninstall_json_config

        monkeypatch.setattr("shutil.which", lambda x: None)

        install_json_config("cursor", project_dir=str(tmp_path))
        result = uninstall_json_config("cursor", project_dir=str(tmp_path))
        assert result is True

        data = json.loads((tmp_path / ".cursor" / "mcp.json").read_text())
        assert "attocode-code-intel" not in data.get("mcpServers", {})

    def test_install_unknown_target(self):
        from attocode.code_intel.installer import install

        result = install("unknown-target")
        assert result is False

    def test_install_claude_no_cli(self, monkeypatch: pytest.MonkeyPatch):
        from attocode.code_intel.installer import install_claude

        monkeypatch.setattr("shutil.which", lambda x: None)

        result = install_claude()
        assert result is False

    def test_install_claude_global_omits_project(self, monkeypatch: pytest.MonkeyPatch):
        """Global install without explicit --project should NOT hard-code --project."""
        import subprocess

        from attocode.code_intel.installer import install_claude

        captured_cmds: list[list[str]] = []

        def fake_which(name: str) -> str | None:
            if name == "claude":
                return "/usr/bin/claude"
            return None  # attocode-code-intel not on PATH

        def fake_run(cmd: list[str], **_kw: object) -> subprocess.CompletedProcess[str]:
            captured_cmds.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0)

        monkeypatch.setattr("shutil.which", fake_which)
        monkeypatch.setattr("attocode.code_intel.installer.subprocess.run", fake_run)

        result = install_claude(project_dir=".", scope="user")
        assert result is True
        assert len(captured_cmds) == 1
        assert "--project" not in captured_cmds[0]

    def test_install_claude_global_with_explicit_project(self, monkeypatch: pytest.MonkeyPatch):
        """Global install with explicit --project should include --project."""
        import subprocess

        from attocode.code_intel.installer import install_claude

        captured_cmds: list[list[str]] = []

        def fake_which(name: str) -> str | None:
            if name == "claude":
                return "/usr/bin/claude"
            return None

        def fake_run(cmd: list[str], **_kw: object) -> subprocess.CompletedProcess[str]:
            captured_cmds.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0)

        monkeypatch.setattr("shutil.which", fake_which)
        monkeypatch.setattr("attocode.code_intel.installer.subprocess.run", fake_run)

        result = install_claude(project_dir="/some/path", scope="user")
        assert result is True
        assert len(captured_cmds) == 1
        assert "--project" in captured_cmds[0]
        assert "/some/path" in captured_cmds[0]

    def test_install_claude_local_includes_project(self, monkeypatch: pytest.MonkeyPatch):
        """Local install should always include --project."""
        import subprocess

        from attocode.code_intel.installer import install_claude

        captured_cmds: list[list[str]] = []

        def fake_which(name: str) -> str | None:
            if name == "claude":
                return "/usr/bin/claude"
            return None

        def fake_run(cmd: list[str], **_kw: object) -> subprocess.CompletedProcess[str]:
            captured_cmds.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0)

        monkeypatch.setattr("shutil.which", fake_which)
        monkeypatch.setattr("attocode.code_intel.installer.subprocess.run", fake_run)

        result = install_claude(project_dir=".", scope="local")
        assert result is True
        assert len(captured_cmds) == 1
        assert "--project" in captured_cmds[0]


# ---------------------------------------------------------------------------
# CLI dispatch
# ---------------------------------------------------------------------------


class TestCLIDispatch:
    def test_dispatch_help(self, capsys: pytest.CaptureFixture[str]):
        from attocode.code_intel.cli import dispatch_code_intel

        dispatch_code_intel(["--help"])
        captured = capsys.readouterr()
        assert "install" in captured.out
        assert "uninstall" in captured.out
        assert "serve" in captured.out

    def test_dispatch_status(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
    ):
        from attocode.code_intel.cli import dispatch_code_intel

        monkeypatch.setattr("shutil.which", lambda x: None)

        dispatch_code_intel(["status"])
        captured = capsys.readouterr()
        assert "attocode-code-intel status" in captured.out

    def test_dispatch_unknown(self):
        from attocode.code_intel.cli import dispatch_code_intel

        with pytest.raises(SystemExit):
            dispatch_code_intel(["bogus"])

    def test_dispatch_install_no_target(self):
        from attocode.code_intel.cli import dispatch_code_intel

        with pytest.raises(SystemExit):
            dispatch_code_intel(["install"])

    def test_parse_opts(self):
        from attocode.code_intel.cli import _parse_opts

        target, project, scope = _parse_opts(["claude", "--project", "/foo", "--global"])
        assert target == "claude"
        assert project == "/foo"
        assert scope == "user"

    def test_parse_opts_defaults(self):
        from attocode.code_intel.cli import _parse_opts

        target, project, scope = _parse_opts(["cursor"])
        assert target == "cursor"
        assert project == "."
        assert scope == "local"


# ---------------------------------------------------------------------------
# CLI dispatch from main CLI
# ---------------------------------------------------------------------------


class TestMainCLIDispatch:
    def test_code_intel_dispatch_in_main_cli(self, monkeypatch: pytest.MonkeyPatch):
        """Verify that `attocode code-intel status` routes to code_intel.cli."""
        dispatched: list[tuple[list[str], bool]] = []

        monkeypatch.setattr(
            "attocode.code_intel.cli.dispatch_code_intel",
            lambda parts, debug=False: dispatched.append((list(parts), debug)),
        )
        monkeypatch.setattr("sys.argv", ["attocode", "code-intel", "status"])

        from attocode.cli import _entry_point

        _entry_point()

        assert len(dispatched) == 1
        assert "status" in dispatched[0][0]

    def test_code_intel_dispatch_with_flags(self, monkeypatch: pytest.MonkeyPatch):
        """Verify flags like --global are passed through, not eaten by Click."""
        dispatched: list[tuple[list[str], bool]] = []

        monkeypatch.setattr(
            "attocode.code_intel.cli.dispatch_code_intel",
            lambda parts, debug=False: dispatched.append((list(parts), debug)),
        )
        monkeypatch.setattr(
            "sys.argv",
            ["attocode", "code-intel", "install", "claude", "--global"],
        )

        from attocode.cli import _entry_point

        _entry_point()

        assert len(dispatched) == 1
        assert dispatched[0][0] == ["install", "claude", "--global"]

    def test_code_intel_dispatch_with_debug(self, monkeypatch: pytest.MonkeyPatch):
        """Verify --debug before code-intel is forwarded."""
        dispatched: list[tuple[list[str], bool]] = []

        monkeypatch.setattr(
            "attocode.code_intel.cli.dispatch_code_intel",
            lambda parts, debug=False: dispatched.append((list(parts), debug)),
        )
        monkeypatch.setattr(
            "sys.argv",
            ["attocode", "--debug", "code-intel", "status"],
        )

        from attocode.cli import _entry_point

        _entry_point()

        assert len(dispatched) == 1
        assert dispatched[0][1] is True  # debug=True
