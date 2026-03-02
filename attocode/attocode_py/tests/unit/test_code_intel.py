"""Tests for attocode.code_intel — MCP server, installer, CLI dispatch."""

from __future__ import annotations

import json
import tomllib
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from attocode.integrations.context.codebase_ast import (
    ClassDef,
    FileAST,
    FunctionDef,
    ImportDef,
    ParamDef,
)
from attocode.integrations.context.codebase_context import FileInfo, RepoMap
from attocode.integrations.context.cross_references import CrossRefIndex

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
# Synthesis tools
# ---------------------------------------------------------------------------


def _build_mock_env(tmp_path, monkeypatch):
    """Shared factory: build realistic mock singletons for synthesis tool tests."""
    import attocode.code_intel.server as srv

    monkeypatch.setenv("ATTOCODE_PROJECT_DIR", str(tmp_path))
    srv._ast_service = None
    srv._context_mgr = None
    srv._code_analyzer = None

    # --- FileInfo objects ---
    files = [
        FileInfo(
            path=str(tmp_path / "src/main.py"),
            relative_path="src/main.py",
            size=5000,
            language="python",
            importance=0.9,
            line_count=200,
        ),
        FileInfo(
            path=str(tmp_path / "src/utils.py"),
            relative_path="src/utils.py",
            size=15000,
            language="python",
            importance=0.7,
            line_count=600,
        ),
        FileInfo(
            path=str(tmp_path / "tests/test_main.py"),
            relative_path="tests/test_main.py",
            size=3000,
            language="python",
            importance=0.3,
            is_test=True,
            line_count=80,
        ),
        FileInfo(
            path=str(tmp_path / "tests/test_utils.py"),
            relative_path="tests/test_utils.py",
            size=2000,
            language="python",
            importance=0.2,
            is_test=True,
            line_count=60,
        ),
        FileInfo(
            path=str(tmp_path / "tests/test_edge.py"),
            relative_path="tests/test_edge.py",
            size=1500,
            language="python",
            importance=0.2,
            is_test=True,
            line_count=50,
        ),
        FileInfo(
            path=str(tmp_path / "pyproject.toml"),
            relative_path="pyproject.toml",
            size=500,
            language="toml",
            importance=0.1,
            is_config=True,
            line_count=30,
        ),
    ]

    # --- RepoMap ---
    repo_map = RepoMap(
        tree="src/\n  main.py\n  utils.py\ntests/\n  test_main.py\n  test_utils.py\n  test_edge.py",
        files=files,
        total_files=6,
        total_lines=1020,
        languages={"python": 5, "toml": 1},
    )

    # --- CrossRefIndex ---
    index = CrossRefIndex(
        file_dependents={
            "src/utils.py": {
                "src/main.py", "tests/test_main.py",
                "src/a.py", "src/b.py", "src/c.py",
            },
        },
        file_dependencies={
            "src/main.py": {"src/utils.py"},
            "tests/test_main.py": {"src/main.py", "src/utils.py"},
        },
        file_symbols={
            "src/main.py": {"main", "cli"},
            "src/utils.py": set(f"fn_{i}" for i in range(25)),
        },
    )

    # --- FileAST entries ---
    main_ast = FileAST(
        path="src/main.py",
        language="python",
        functions=[
            FunctionDef(
                name="main",
                start_line=1,
                end_line=20,
                return_type="None",
                parameters=[],
                decorators=["click.command"],
                docstring="Entry point.",
            ),
            FunctionDef(
                name="cli",
                start_line=22,
                end_line=50,
                return_type="int",
                parameters=[
                    ParamDef(name="args", type_annotation="list[str]"),
                ],
                is_async=True,
                docstring="Parse CLI args.",
            ),
        ],
        classes=[],
        imports=[
            ImportDef(module="click", is_from=False, line=1),
            ImportDef(module="src.utils", names=["helper"], is_from=True, line=2),
        ],
        top_level_vars=["__all__"],
        line_count=200,
    )

    utils_ast = FileAST(
        path="src/utils.py",
        language="python",
        functions=[
            FunctionDef(
                name="helper",
                start_line=10,
                end_line=30,
                return_type="str",
                parameters=[
                    ParamDef(name="value", type_annotation="int"),
                ],
                docstring="A helper function.",
            ),
            FunctionDef(
                name="_parse_data",
                start_line=32,
                end_line=60,
                parameters=[
                    ParamDef(name="raw"),
                ],
                visibility="private",
            ),
            FunctionDef(
                name="big_function",
                start_line=62,
                end_line=162,
                parameters=[
                    ParamDef(name="a", type_annotation="int"),
                    ParamDef(name="b", type_annotation="str"),
                    ParamDef(name="c"),
                    ParamDef(name="d"),
                    ParamDef(name="e"),
                    ParamDef(name="f"),
                    ParamDef(name="g"),
                    ParamDef(name="h"),
                ],
            ),
        ] + [
            FunctionDef(
                name=f"fn_{i}",
                start_line=164 + i * 20,
                end_line=182 + i * 20,
                return_type="str" if i < 15 else None,
                docstring=f"Function {i}." if i < 15 else None,
            )
            for i in range(22)
        ],
        classes=[
            ClassDef(
                name="BaseProcessor",
                start_line=500,
                end_line=580,
                bases=[],
                decorators=["dataclass(slots=True)"],
                docstring="Base processor class.",
                methods=[
                    FunctionDef(
                        name="process",
                        start_line=510,
                        end_line=530,
                        is_method=True,
                        return_type="None",
                        parameters=[ParamDef(name="self")],
                        decorators=[],
                        is_staticmethod=False,
                    ),
                    FunctionDef(
                        name="from_config",
                        start_line=532,
                        end_line=540,
                        is_method=True,
                        return_type="BaseProcessor",
                        parameters=[ParamDef(name="cls")],
                        decorators=["classmethod"],
                        is_classmethod=True,
                    ),
                    FunctionDef(
                        name="name",
                        start_line=542,
                        end_line=544,
                        is_method=True,
                        return_type="str",
                        parameters=[ParamDef(name="self")],
                        decorators=["property"],
                        is_property=True,
                    ),
                ],
                is_abstract=False,
            ),
            ClassDef(
                name="AdvancedProcessor",
                start_line=582,
                end_line=600,
                bases=["BaseProcessor"],
                decorators=[],
                is_abstract=True,
            ),
            ClassDef(
                name="AgentError",
                start_line=602,
                end_line=620,
                bases=["Exception"],
                decorators=[],
            ),
            ClassDef(
                name="LLMError",
                start_line=622,
                end_line=640,
                bases=["AgentError"],
                decorators=[],
            ),
        ],
        imports=[
            ImportDef(module="os", is_from=False, line=1),
            ImportDef(module="dataclasses", names=["dataclass"], is_from=True, line=2),
            ImportDef(module=".helpers", names=["x"], is_from=True, line=3),
        ],
        line_count=600,
    )

    # Test-file ASTs with different conventions (0% type hints, 0% docstrings)
    test_ast = FileAST(
        path="tests/test_main.py",
        language="python",
        functions=[
            FunctionDef(
                name="test_basic",
                start_line=1,
                end_line=10,
                parameters=[],
            ),
            FunctionDef(
                name="test_advanced",
                start_line=12,
                end_line=25,
                parameters=[],
            ),
            FunctionDef(
                name="test_edge",
                start_line=27,
                end_line=40,
                parameters=[],
            ),
        ],
        classes=[],
        imports=[
            ImportDef(module="pytest", is_from=False, line=1),
        ],
        line_count=80,
    )

    test_utils_ast = FileAST(
        path="tests/test_utils.py",
        language="python",
        functions=[
            FunctionDef(name="test_helper", start_line=1, end_line=15, parameters=[]),
            FunctionDef(name="test_parse", start_line=17, end_line=30, parameters=[]),
        ],
        classes=[],
        imports=[ImportDef(module="pytest", is_from=False, line=1)],
        line_count=60,
    )

    test_edge_ast = FileAST(
        path="tests/test_edge.py",
        language="python",
        functions=[
            FunctionDef(name="test_empty", start_line=1, end_line=8, parameters=[]),
            FunctionDef(name="test_boundary", start_line=10, end_line=20, parameters=[]),
        ],
        classes=[],
        imports=[ImportDef(module="pytest", is_from=False, line=1)],
        line_count=50,
    )

    ast_cache = {
        "src/main.py": main_ast,
        "src/utils.py": utils_ast,
        "tests/test_main.py": test_ast,
        "tests/test_utils.py": test_utils_ast,
        "tests/test_edge.py": test_edge_ast,
    }

    # --- Wire mocks ---
    ctx_mock = MagicMock()
    ctx_mock._files = files
    ctx_mock.get_repo_map.return_value = repo_map

    svc_mock = MagicMock()
    svc_mock._index = index
    svc_mock._ast_cache = ast_cache
    svc_mock.initialized = True

    srv._context_mgr = ctx_mock
    srv._ast_service = svc_mock

    # Create a pyproject.toml so _detect_project_name works
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "my-cool-project"\n')

    return srv, ctx_mock, svc_mock


class TestSynthesisTools:
    """Test project_summary, hotspots, and conventions tools."""

    @pytest.fixture(autouse=True)
    def _setup_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        self.srv, self.ctx_mock, self.svc_mock = _build_mock_env(tmp_path, monkeypatch)
        self.tmp_path = tmp_path
        yield
        self.srv._ast_service = None
        self.srv._context_mgr = None
        self.srv._code_analyzer = None

    # -- project_summary --

    def test_project_summary_basic(self):
        from attocode.code_intel.server import project_summary

        result = project_summary(max_tokens=4000)
        assert "my-cool-project" in result
        assert "python" in result.lower()
        assert "src/main.py" in result
        assert "1,020" in result  # total lines

    def test_project_summary_empty(self, monkeypatch: pytest.MonkeyPatch):
        self.ctx_mock._files = []
        from attocode.code_intel.server import project_summary

        result = project_summary()
        assert "No files discovered" in result

    def test_project_summary_no_deps(self):
        """Works when CrossRefIndex has no dependency data."""
        self.svc_mock._index = CrossRefIndex()  # empty
        from attocode.code_intel.server import project_summary

        result = project_summary()
        assert "my-cool-project" in result
        # Should still have overview and directories, just no hub/layer sections

    # -- hotspots --

    def test_hotspots_basic(self):
        from attocode.code_intel.server import hotspots

        result = hotspots(top_n=15)
        assert "hotspots" in result.lower()
        assert "src/utils.py" in result
        assert "fan-in=" in result

    def test_hotspots_empty(self, monkeypatch: pytest.MonkeyPatch):
        self.ctx_mock._files = []
        from attocode.code_intel.server import hotspots

        result = hotspots()
        assert "No files discovered" in result

    def test_hotspots_top_n(self):
        from attocode.code_intel.server import hotspots

        result = hotspots(top_n=1)
        # Split at "Longest functions" to isolate the file hotspots section
        if "Longest functions" in result:
            file_section = result.split("Longest functions")[0]
        else:
            file_section = result
        # Should only show 1 ranked file entry
        ranked_lines = [
            line for line in file_section.split("\n")
            if line.strip().startswith("1.")
        ]
        assert len(ranked_lines) == 1
        # Should NOT have a "2." entry in file section
        assert "  2." not in file_section

    def test_hotspots_categories(self):
        from attocode.code_intel.server import hotspots

        result = hotspots(top_n=15)
        # utils.py has many symbols + 600 lines and 5 dependents
        # With adaptive thresholds (P90-based), utils.py should still stand out
        assert "hub" in result or "god-file" in result

    def test_hotspots_orphans(self):
        """Files with no imports/importers are flagged as orphans."""
        # Add an orphan file
        orphan = FileInfo(
            path=str(self.tmp_path / "src/orphan.py"),
            relative_path="src/orphan.py",
            size=1000,
            language="python",
            importance=0.2,
            line_count=50,
        )
        self.ctx_mock._files = list(self.ctx_mock._files) + [orphan]
        # Ensure orphan has no deps in index
        # (it's not in file_dependents or file_dependencies by default)

        from attocode.code_intel.server import hotspots

        result = hotspots()
        assert "Orphan" in result
        assert "src/orphan.py" in result

    # -- conventions --

    def test_conventions_basic(self):
        from attocode.code_intel.server import conventions

        result = conventions()
        assert "Naming" in result
        assert "snake_case" in result
        assert "Type hints" in result
        assert "Imports" in result

    def test_conventions_empty(self, monkeypatch: pytest.MonkeyPatch):
        self.svc_mock._ast_cache = {}
        from attocode.code_intel.server import conventions

        result = conventions()
        assert "No files parsed" in result

    def test_conventions_async(self):
        from attocode.code_intel.server import conventions

        result = conventions()
        # main.py has 1 async fn (cli), total fns > 0
        assert "Async" in result or "async" in result

    def test_conventions_decorators(self):
        from attocode.code_intel.server import conventions

        result = conventions()
        assert "decorator" in result.lower()
        assert "click.command" in result or "dataclass" in result

    def test_conventions_class_patterns(self):
        from attocode.code_intel.server import conventions

        result = conventions()
        assert "dataclass" in result.lower()
        # AdvancedProcessor has is_abstract=True
        assert "abstract" in result.lower()
        # BaseProcessor is a base class used by AdvancedProcessor
        assert "BaseProcessor" in result

    # -- new hotspots tests --

    def test_hotspots_percentile_scoring(self):
        """Composite scores should be in 0-1 range (percentile-based)."""
        from attocode.code_intel.server import _compute_file_metrics

        files = list(self.ctx_mock._files)
        svc = self.svc_mock
        metrics = _compute_file_metrics(files, svc._index, svc._ast_cache)
        for m in metrics:
            assert 0.0 <= m.composite <= 1.0, f"{m.path} score={m.composite} out of range"

    def test_hotspots_adaptive_thresholds(self):
        """Categories should adapt — a small project shouldn't label everything."""
        from attocode.code_intel.server import _compute_file_metrics

        files = list(self.ctx_mock._files)
        svc = self.svc_mock
        metrics = _compute_file_metrics(files, svc._index, svc._ast_cache)
        # Not all files should be categorized
        uncategorized = [m for m in metrics if not m.categories]
        # At least one file should have no categories (main.py is moderate)
        assert len(uncategorized) >= 1 or len(metrics) <= 1

    def test_hotspots_function_level(self):
        """Function-level hotspots section should appear in output."""
        from attocode.code_intel.server import hotspots

        result = hotspots(top_n=15)
        assert "Longest functions" in result
        # big_function is 101 lines — should appear
        assert "big_function" in result

    def test_hotspots_public_api(self):
        """pub= should appear in output for each hotspot entry."""
        from attocode.code_intel.server import hotspots

        result = hotspots(top_n=15)
        assert "pub=" in result

    # -- new conventions tests --

    def test_conventions_per_directory(self):
        """Divergence section should appear when dirs differ from project norm."""
        from attocode.code_intel.server import conventions

        result = conventions()
        # tests/ has 3 files with 0% type hints and 0% docstrings,
        # while src/ has typed returns and docstrings — should trigger divergence
        assert "Convention divergence" in result
        assert "tests/" in result

    def test_conventions_error_hierarchy(self):
        """Exception subclasses should be detected and reported."""
        from attocode.code_intel.server import conventions

        result = conventions()
        assert "Error hierarchy" in result
        assert "AgentError" in result

    def test_conventions_dunder_all(self):
        """__all__ usage should be counted."""
        from attocode.code_intel.server import conventions

        result = conventions()
        assert "__all__" in result

    def test_conventions_slots_detection(self):
        """slots=True count should appear in output."""
        from attocode.code_intel.server import conventions

        result = conventions()
        assert "slots=True" in result

    def test_conventions_visibility(self):
        """Private function percentage should be reported."""
        from attocode.code_intel.server import conventions

        result = conventions()
        # _parse_data has visibility="private"
        assert "Visibility" in result
        assert "private" in result.lower()

    def test_conventions_method_types(self):
        """staticmethod/classmethod/property counts should appear."""
        from attocode.code_intel.server import conventions

        result = conventions()
        assert "Method types" in result
        assert "@classmethod" in result
        assert "@property" in result


class TestPercentileRanksEdgeCases:
    """Direct unit tests for _percentile_ranks helper edge cases."""

    def test_empty_list(self):
        from attocode.code_intel.server import _percentile_ranks

        assert _percentile_ranks([]) == []

    def test_single_element(self):
        from attocode.code_intel.server import _percentile_ranks

        result = _percentile_ranks([42.0])
        assert result == [0.0]

    def test_all_same_values(self):
        from attocode.code_intel.server import _percentile_ranks

        result = _percentile_ranks([5.0, 5.0, 5.0, 5.0])
        # All tied — all should get the same percentile rank
        assert len(result) == 4
        assert all(r == result[0] for r in result)

    def test_strictly_increasing(self):
        from attocode.code_intel.server import _percentile_ranks

        result = _percentile_ranks([1.0, 2.0, 3.0, 4.0])
        assert len(result) == 4
        # First should be 0.0 (lowest), last should be 1.0 (highest)
        assert result[0] == 0.0
        assert result[3] == 1.0
        # Monotonically increasing
        assert result[0] < result[1] < result[2] < result[3]

    def test_two_elements(self):
        from attocode.code_intel.server import _percentile_ranks

        result = _percentile_ranks([10.0, 20.0])
        assert result[0] == 0.0
        assert result[1] == 1.0


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

    def test_install_codex_local(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from attocode.code_intel.installer import install_codex

        monkeypatch.setattr("shutil.which", lambda x: None)

        result = install_codex(project_dir=str(tmp_path))
        assert result is True

        config_path = tmp_path / ".codex" / "config.toml"
        assert config_path.exists()

        data = tomllib.loads(config_path.read_text())
        assert "attocode-code-intel" in data["mcp_servers"]
        server = data["mcp_servers"]["attocode-code-intel"]
        assert "--project" in server["args"]

    def test_install_codex_user(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from attocode.code_intel.installer import install_codex

        monkeypatch.setattr("shutil.which", lambda x: None)
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

        result = install_codex(project_dir="/some/project", scope="user")
        assert result is True

        config_path = tmp_path / ".codex" / "config.toml"
        assert config_path.exists()

        data = tomllib.loads(config_path.read_text())
        assert "attocode-code-intel" in data["mcp_servers"]

    def test_install_codex_merges_existing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        import tomli_w

        from attocode.code_intel.installer import install_codex

        monkeypatch.setattr("shutil.which", lambda x: None)

        # Pre-existing config with another server
        codex_dir = tmp_path / ".codex"
        codex_dir.mkdir()
        existing = {"mcp_servers": {"other-server": {"command": "other", "args": []}}}
        (codex_dir / "config.toml").write_text(tomli_w.dumps(existing))

        install_codex(project_dir=str(tmp_path))

        data = tomllib.loads((codex_dir / "config.toml").read_text())
        assert "other-server" in data["mcp_servers"]
        assert "attocode-code-intel" in data["mcp_servers"]

    def test_uninstall_codex(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from attocode.code_intel.installer import install_codex, uninstall_codex

        monkeypatch.setattr("shutil.which", lambda x: None)

        install_codex(project_dir=str(tmp_path))
        result = uninstall_codex(project_dir=str(tmp_path))
        assert result is True

        data = tomllib.loads((tmp_path / ".codex" / "config.toml").read_text())
        assert "attocode-code-intel" not in data.get("mcp_servers", {})

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
