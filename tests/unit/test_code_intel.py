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
        srv._semantic_search = None
        srv._memory_store = None
        yield
        srv._ast_service = None
        srv._context_mgr = None
        srv._code_analyzer = None
        srv._semantic_search = None
        if srv._memory_store is not None:
            srv._memory_store.close()
            srv._memory_store = None

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
        svc.search_symbol.return_value = [
            (
                SymbolLocation(
                    name="MyClass",
                    qualified_name="MyClass",
                    kind="class",
                    file_path="b.py",
                    start_line=5,
                    end_line=50,
                ),
                0.98,
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

        svc = self._make_mock_ast_service()
        srv._ast_service = svc

        result = search_symbols("MyClass", limit=5, kind="class")
        assert "MyClass" in result
        assert "class" in result
        assert "b.py" in result
        assert "[98%]" in result
        svc.search_symbol.assert_called_once_with("MyClass", limit=5, kind_filter="class")

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

    # -- VS Code --

    def test_install_json_vscode(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from attocode.code_intel.installer import install_json_config

        monkeypatch.setattr("shutil.which", lambda x: None)

        result = install_json_config("vscode", project_dir=str(tmp_path))
        assert result is True

        config_path = tmp_path / ".vscode" / "mcp.json"
        assert config_path.exists()

        data = json.loads(config_path.read_text())
        assert "attocode-code-intel" in data["mcpServers"]
        server = data["mcpServers"]["attocode-code-intel"]
        assert "--project" in server["args"]

    def test_uninstall_json_vscode(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from attocode.code_intel.installer import install_json_config, uninstall_json_config

        monkeypatch.setattr("shutil.which", lambda x: None)

        install_json_config("vscode", project_dir=str(tmp_path))
        result = uninstall_json_config("vscode", project_dir=str(tmp_path))
        assert result is True

        data = json.loads((tmp_path / ".vscode" / "mcp.json").read_text())
        assert "attocode-code-intel" not in data.get("mcpServers", {})

    # -- Claude Desktop --

    def test_install_claude_desktop(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from attocode.code_intel.installer import install_claude_desktop

        monkeypatch.setattr("shutil.which", lambda x: None)
        monkeypatch.setattr(
            "attocode.code_intel.installer._get_user_config_dir",
            lambda app: tmp_path / "claude-desktop" if app == "claude-desktop" else None,
        )

        result = install_claude_desktop(project_dir=str(tmp_path))
        assert result is True

        config_path = tmp_path / "claude-desktop" / "claude_desktop_config.json"
        assert config_path.exists()

        data = json.loads(config_path.read_text())
        assert "attocode-code-intel" in data["mcpServers"]

    def test_uninstall_claude_desktop(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from attocode.code_intel.installer import install_claude_desktop, uninstall_claude_desktop

        monkeypatch.setattr("shutil.which", lambda x: None)
        monkeypatch.setattr(
            "attocode.code_intel.installer._get_user_config_dir",
            lambda app: tmp_path / "claude-desktop" if app == "claude-desktop" else None,
        )

        install_claude_desktop(project_dir=str(tmp_path))
        result = uninstall_claude_desktop()
        assert result is True

        data = json.loads(
            (tmp_path / "claude-desktop" / "claude_desktop_config.json").read_text()
        )
        assert "attocode-code-intel" not in data.get("mcpServers", {})

    def test_install_claude_desktop_unsupported_platform(self, monkeypatch: pytest.MonkeyPatch):
        from attocode.code_intel.installer import install_claude_desktop

        monkeypatch.setattr(
            "attocode.code_intel.installer._get_user_config_dir",
            lambda app: None,
        )

        result = install_claude_desktop()
        assert result is False

    # -- Cline --

    def test_install_cline(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from attocode.code_intel.installer import install_cline

        monkeypatch.setattr("shutil.which", lambda x: None)
        monkeypatch.setattr(
            "attocode.code_intel.installer._get_user_config_dir",
            lambda app: tmp_path / "cline" if app == "cline" else None,
        )

        result = install_cline(project_dir=str(tmp_path))
        assert result is True

        config_path = tmp_path / "cline" / "cline_mcp_settings.json"
        assert config_path.exists()

        data = json.loads(config_path.read_text())
        assert "attocode-code-intel" in data["mcpServers"]

    def test_uninstall_cline(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from attocode.code_intel.installer import install_cline, uninstall_cline

        monkeypatch.setattr("shutil.which", lambda x: None)
        monkeypatch.setattr(
            "attocode.code_intel.installer._get_user_config_dir",
            lambda app: tmp_path / "cline" if app == "cline" else None,
        )

        install_cline(project_dir=str(tmp_path))
        result = uninstall_cline()
        assert result is True

        data = json.loads(
            (tmp_path / "cline" / "cline_mcp_settings.json").read_text()
        )
        assert "attocode-code-intel" not in data.get("mcpServers", {})

    # -- Zed --

    def test_install_zed_local(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from attocode.code_intel.installer import install_zed

        monkeypatch.setattr("shutil.which", lambda x: None)

        result = install_zed(project_dir=str(tmp_path), scope="local")
        assert result is True

        config_path = tmp_path / ".zed" / "settings.json"
        assert config_path.exists()

        data = json.loads(config_path.read_text())
        assert "attocode-code-intel" in data["context_servers"]
        entry = data["context_servers"]["attocode-code-intel"]
        assert "command" in entry
        assert "path" in entry["command"]
        assert "args" in entry["command"]

    def test_install_zed_user(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from attocode.code_intel.installer import install_zed

        monkeypatch.setattr("shutil.which", lambda x: None)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

        result = install_zed(project_dir=str(tmp_path), scope="user")
        assert result is True

        config_path = tmp_path / "xdg" / "zed" / "settings.json"
        assert config_path.exists()

        data = json.loads(config_path.read_text())
        assert "attocode-code-intel" in data["context_servers"]

    def test_uninstall_zed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from attocode.code_intel.installer import install_zed, uninstall_zed

        monkeypatch.setattr("shutil.which", lambda x: None)

        install_zed(project_dir=str(tmp_path), scope="local")
        result = uninstall_zed(project_dir=str(tmp_path), scope="local")
        assert result is True

        data = json.loads((tmp_path / ".zed" / "settings.json").read_text())
        assert "attocode-code-intel" not in data.get("context_servers", {})

    def test_install_zed_merges_existing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from attocode.code_intel.installer import install_zed

        monkeypatch.setattr("shutil.which", lambda x: None)

        # Pre-existing settings
        zed_dir = tmp_path / ".zed"
        zed_dir.mkdir()
        existing = {
            "theme": "One Dark",
            "context_servers": {"other-server": {"command": {"path": "other"}}},
        }
        (zed_dir / "settings.json").write_text(json.dumps(existing))

        install_zed(project_dir=str(tmp_path), scope="local")

        data = json.loads((zed_dir / "settings.json").read_text())
        assert data["theme"] == "One Dark"
        assert "other-server" in data["context_servers"]
        assert "attocode-code-intel" in data["context_servers"]

    # -- IntelliJ / OpenCode (manual instructions) --

    def test_print_manual_instructions_intellij(self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch):
        from attocode.code_intel.installer import print_manual_instructions

        monkeypatch.setattr("shutil.which", lambda x: None)

        result = print_manual_instructions("intellij")
        assert result is True

        captured = capsys.readouterr()
        assert "IntelliJ" in captured.out
        assert "MCP Servers" in captured.out

    def test_print_manual_instructions_opencode(self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch):
        from attocode.code_intel.installer import print_manual_instructions

        monkeypatch.setattr("shutil.which", lambda x: None)

        result = print_manual_instructions("opencode")
        assert result is True

        captured = capsys.readouterr()
        assert "OpenCode" in captured.out
        assert "mcpServers" in captured.out

    def test_install_dispatch_intellij(self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch):
        """install('intellij') should print instructions, not fail."""
        from attocode.code_intel.installer import install

        monkeypatch.setattr("shutil.which", lambda x: None)

        result = install("intellij")
        assert result is True

        captured = capsys.readouterr()
        assert "IntelliJ" in captured.out

    def test_uninstall_dispatch_manual_target(self, capsys: pytest.CaptureFixture[str]):
        """uninstall('intellij') should succeed with a message."""
        from attocode.code_intel.installer import uninstall

        result = uninstall("intellij")
        assert result is True

        captured = capsys.readouterr()
        assert "manual" in captured.out.lower()

    # -- _get_user_config_dir --

    def test_get_user_config_dir_claude_desktop_darwin(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        from attocode.code_intel.installer import _get_user_config_dir

        monkeypatch.setattr("attocode.code_intel.installer.platform.system", lambda: "Darwin")
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

        result = _get_user_config_dir("claude-desktop")
        assert result is not None
        assert "Application Support" in str(result)
        assert "Claude" in str(result)

    def test_get_user_config_dir_claude_desktop_linux(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        from attocode.code_intel.installer import _get_user_config_dir

        monkeypatch.setattr("attocode.code_intel.installer.platform.system", lambda: "Linux")
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

        result = _get_user_config_dir("claude-desktop")
        assert result is not None
        assert ".config" in str(result)
        assert "Claude" in str(result)

    def test_get_user_config_dir_cline_darwin(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        from attocode.code_intel.installer import _get_user_config_dir

        monkeypatch.setattr("attocode.code_intel.installer.platform.system", lambda: "Darwin")
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

        result = _get_user_config_dir("cline")
        assert result is not None
        assert "globalStorage" in str(result)
        assert "saoudrizwan.claude-dev" in str(result)

    def test_get_user_config_dir_unknown_app(self):
        from attocode.code_intel.installer import _get_user_config_dir

        result = _get_user_config_dir("unknown-app")
        assert result is None


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

    def test_status_shows_all_targets(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
    ):
        """Status output should mention all supported targets."""
        from attocode.code_intel.cli import dispatch_code_intel

        monkeypatch.setattr("shutil.which", lambda x: None)

        dispatch_code_intel(["status"])
        captured = capsys.readouterr()
        for target_name in ["Claude Code", "Cursor", "Windsurf", "VS Code", "Codex",
                            "Claude Desktop", "Cline", "Zed"]:
            assert target_name in captured.out, f"Missing '{target_name}' in status output"

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

        target, project, scope, hooks = _parse_opts(["claude", "--project", "/foo", "--global"])
        assert target == "claude"
        assert project == "/foo"
        assert scope == "user"
        assert hooks is False

    def test_parse_opts_defaults(self):
        from attocode.code_intel.cli import _parse_opts

        target, project, scope, hooks = _parse_opts(["cursor"])
        assert target == "cursor"
        assert project == "."
        assert scope == "local"
        assert hooks is False


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


# ---------------------------------------------------------------------------
# PageRank importance scoring (P2)
# ---------------------------------------------------------------------------


class TestPageRank:
    """Test PageRank scoring on the DependencyGraph."""

    def test_empty_graph(self):
        from attocode.integrations.context.codebase_context import DependencyGraph

        g = DependencyGraph()
        scores = g.pagerank()
        assert scores == {}

    def test_single_node(self):
        from attocode.integrations.context.codebase_context import DependencyGraph

        g = DependencyGraph()
        g.add_edge("a.py", "b.py")
        scores = g.pagerank()
        assert "a.py" in scores
        assert "b.py" in scores
        # b.py is imported by a.py, so b.py should have higher PageRank
        assert scores["b.py"] >= scores["a.py"]

    def test_hub_file_ranks_highest(self):
        from attocode.integrations.context.codebase_context import DependencyGraph

        g = DependencyGraph()
        # types.py is imported by many files
        for i in range(10):
            g.add_edge(f"module{i}.py", "types.py")
        # utils.py imported by fewer
        for i in range(3):
            g.add_edge(f"module{i}.py", "utils.py")

        scores = g.pagerank()
        assert scores["types.py"] > scores["utils.py"]
        # types.py should be the highest scored
        assert scores["types.py"] == 1.0  # normalized max

    def test_transitive_importance(self):
        """File imported by important files should rank higher than
        file imported by leaf files."""
        from attocode.integrations.context.codebase_context import DependencyGraph

        g = DependencyGraph()
        # hub.py is imported by many
        for i in range(10):
            g.add_edge(f"m{i}.py", "hub.py")
        # hub.py imports core.py (transitive importance)
        g.add_edge("hub.py", "core.py")
        # leaf.py also imports helper.py
        g.add_edge("leaf.py", "helper.py")

        scores = g.pagerank()
        # core.py should rank higher than helper.py because hub.py (important) imports it
        assert scores["core.py"] > scores["helper.py"]

    def test_convergence(self):
        from attocode.integrations.context.codebase_context import DependencyGraph

        g = DependencyGraph()
        # Cycle
        g.add_edge("a.py", "b.py")
        g.add_edge("b.py", "c.py")
        g.add_edge("c.py", "a.py")

        scores = g.pagerank()
        # All nodes should have similar scores in a cycle
        values = list(scores.values())
        assert max(values) - min(values) < 0.2

    def test_normalized_range(self):
        from attocode.integrations.context.codebase_context import DependencyGraph

        g = DependencyGraph()
        for i in range(20):
            g.add_edge(f"src{i}.py", "base.py")
            if i > 0:
                g.add_edge(f"src{i}.py", f"src{i-1}.py")

        scores = g.pagerank()
        for v in scores.values():
            assert 0.0 <= v <= 1.0


# ---------------------------------------------------------------------------
# Bootstrap tool (P1)
# ---------------------------------------------------------------------------


class TestBootstrapTool:
    """Test the bootstrap all-in-one orientation tool."""

    @pytest.fixture(autouse=True)
    def _setup_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ATTOCODE_PROJECT_DIR", str(tmp_path))

        import attocode.code_intel.server as srv

        srv._ast_service = None
        srv._context_mgr = None
        srv._code_analyzer = None
        srv._explorer = None
        srv._semantic_search = None
        yield
        srv._ast_service = None
        srv._context_mgr = None
        srv._code_analyzer = None
        srv._explorer = None
        srv._semantic_search = None

    def _make_mock_context(self, file_count: int):
        """Create mock context manager with given file count."""
        files = []
        for i in range(file_count):
            fi = MagicMock()
            fi.relative_path = f"src/mod{i}.py"
            fi.importance = 0.5 + (i % 5) * 0.1
            fi.language = "python"
            fi.line_count = 100
            fi.is_test = False
            fi.is_config = False
            fi.size = 5000
            files.append(fi)

        ctx = MagicMock()
        ctx._files = files
        return ctx

    def _make_mock_services(self, file_count: int):
        """Set up mocked server singletons for bootstrap tests."""
        import attocode.code_intel.server as srv

        ctx = self._make_mock_context(file_count)

        # Need a real-ish RepoMap for project_summary to work
        repo_map = RepoMap(
            tree="src/\n  mod.py",
            files=[],
            total_files=file_count,
            total_lines=file_count * 100,
            languages={"python": file_count},
        )
        ctx.get_repo_map = MagicMock(return_value=repo_map)

        srv._context_mgr = ctx

        svc = MagicMock()
        svc.initialized = True
        svc._ast_cache = {}
        svc._index = MagicMock()
        svc._index.file_dependents = {}
        svc._index.file_dependencies = {}
        svc._index.definitions = {}
        svc._index.file_symbols = {}
        srv._ast_service = svc

        return ctx, svc

    def test_bootstrap_small_codebase(self):
        import attocode.code_intel.server as srv

        self._make_mock_services(50)

        result = srv.bootstrap(max_tokens=4000)
        # Should contain project overview
        assert "Project:" in result or "Overview" in result or "Navigation" in result

    def test_bootstrap_detects_large_codebase(self):
        import attocode.code_intel.server as srv

        self._make_mock_services(3000)

        # Mock explorer for large codebase path
        explorer = MagicMock()
        explorer.explore.return_value = MagicMock()
        explorer.format_result.return_value = "src/ (3000 files)"
        srv._explorer = explorer

        result = srv.bootstrap(max_tokens=4000)
        assert "Navigation" in result
        # Should mention NOT using repo_map
        assert "do NOT" in result or "drill" in result.lower()

    def test_bootstrap_empty_codebase(self):
        import attocode.code_intel.server as srv

        ctx = MagicMock()
        ctx._files = []
        srv._context_mgr = ctx

        svc = MagicMock()
        svc.initialized = True
        svc._ast_cache = {}
        srv._ast_service = svc

        result = srv.bootstrap()
        assert "No files" in result


# ---------------------------------------------------------------------------
# Relevant context tool (P3)
# ---------------------------------------------------------------------------


class TestRelevantContextTool:
    """Test the relevant_context subgraph capsule tool."""

    @pytest.fixture(autouse=True)
    def _setup_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ATTOCODE_PROJECT_DIR", str(tmp_path))

        import attocode.code_intel.server as srv

        srv._ast_service = None
        srv._context_mgr = None
        yield
        srv._ast_service = None
        srv._context_mgr = None

    def test_relevant_context_basic(self):
        import attocode.code_intel.server as srv

        # Mock AST service
        svc = MagicMock()
        svc.initialized = True
        svc._to_rel.side_effect = lambda p: p
        svc.get_dependencies.return_value = {"dep1.py", "dep2.py"}
        svc.get_dependents.return_value = {"user1.py"}

        file_ast = MagicMock()
        file_ast.functions = []
        file_ast.classes = []
        svc._ast_cache = {
            "target.py": file_ast,
            "dep1.py": file_ast,
            "dep2.py": file_ast,
            "user1.py": file_ast,
        }
        srv._ast_service = svc

        # Mock context manager
        fi = MagicMock()
        fi.relative_path = "target.py"
        fi.importance = 0.8
        fi.language = "python"
        fi.line_count = 200

        fi2 = MagicMock()
        fi2.relative_path = "dep1.py"
        fi2.importance = 0.6
        fi2.language = "python"
        fi2.line_count = 100

        fi3 = MagicMock()
        fi3.relative_path = "dep2.py"
        fi3.importance = 0.5
        fi3.language = "python"
        fi3.line_count = 50

        fi4 = MagicMock()
        fi4.relative_path = "user1.py"
        fi4.importance = 0.7
        fi4.language = "python"
        fi4.line_count = 150

        ctx = MagicMock()
        ctx._files = [fi, fi2, fi3, fi4]
        srv._context_mgr = ctx

        result = srv.relevant_context(["target.py"])
        assert "target.py" in result
        assert "dep1.py" in result
        assert "dep2.py" in result
        assert "user1.py" in result
        assert "center" in result

    def test_relevant_context_empty_files(self):
        import attocode.code_intel.server as srv

        svc = MagicMock()
        svc._to_rel.return_value = ""
        srv._ast_service = svc

        ctx = MagicMock()
        ctx._files = []
        srv._context_mgr = ctx

        result = srv.relevant_context([])
        assert "No valid files" in result

    def test_relevant_context_depth_cap(self):
        import attocode.code_intel.server as srv

        svc = MagicMock()
        svc.initialized = True
        svc._to_rel.side_effect = lambda p: p
        svc.get_dependencies.return_value = set()
        svc.get_dependents.return_value = set()
        svc._ast_cache = {}
        srv._ast_service = svc

        ctx = MagicMock()
        ctx._files = []
        srv._context_mgr = ctx

        # depth > 2 should be capped to 2
        result = srv.relevant_context(["a.py"], depth=5)
        assert "depth=2" in result


# ---------------------------------------------------------------------------
# Scoped conventions (P5)
# ---------------------------------------------------------------------------


class TestScopedConventions:
    """Test path-scoped convention detection."""

    @pytest.fixture(autouse=True)
    def _setup_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ATTOCODE_PROJECT_DIR", str(tmp_path))

        import attocode.code_intel.server as srv

        srv._ast_service = None
        srv._context_mgr = None
        yield
        srv._ast_service = None
        srv._context_mgr = None

    def _make_file_ast(self, funcs: list[str], typed: int = 0, docstrings: int = 0):
        """Create a FileAST-like mock for convention tests."""
        functions = []
        for i, name in enumerate(funcs):
            fn = MagicMock()
            fn.name = name
            fn.return_type = "str" if i < typed else ""
            fn.docstring = "A function." if i < docstrings else ""
            fn.is_async = False
            fn.visibility = "public"
            fn.is_staticmethod = False
            fn.is_classmethod = False
            fn.is_property = False
            fn.decorators = []
            fn.parameters = []
            functions.append(fn)

        ast = MagicMock()
        ast.functions = functions
        ast.classes = []
        ast.imports = []
        ast.top_level_vars = []
        ast.line_count = 100
        return ast

    def test_scoped_conventions_filters_by_path(self):
        import attocode.code_intel.server as srv

        # Create two directories with different styles
        core_ast = self._make_file_ast(["handle_request", "validate_input"], typed=2, docstrings=2)
        tools_ast = self._make_file_ast(["run_tool", "get_result"], typed=0, docstrings=0)

        svc = MagicMock()
        svc._ast_cache = {
            "src/core/handler.py": core_ast,
            "src/core/validator.py": core_ast,
            "src/core/router.py": core_ast,
            "src/tools/bash.py": tools_ast,
            "src/tools/grep.py": tools_ast,
            "src/tools/glob.py": tools_ast,
        }
        srv._ast_service = svc

        fi_list = []
        for path in svc._ast_cache:
            fi = MagicMock()
            fi.relative_path = path
            fi.importance = 0.6
            fi_list.append(fi)

        ctx = MagicMock()
        ctx._files = fi_list
        srv._context_mgr = ctx

        # Test scoped to src/core
        result = srv.conventions(path="src/core")
        assert "src/core/" in result
        assert "3 files" in result

    def test_scoped_conventions_empty_dir(self):
        import attocode.code_intel.server as srv

        svc = MagicMock()
        svc._ast_cache = {"src/main.py": object()}
        srv._ast_service = svc

        ctx = MagicMock()
        fi = MagicMock()
        fi.relative_path = "src/main.py"
        fi.importance = 0.6
        ctx._files = [fi]
        srv._context_mgr = ctx

        result = srv.conventions(path="nonexistent")
        assert "No parsed files found" in result


# ---------------------------------------------------------------------------
# Tree-sitter parser (P4)
# ---------------------------------------------------------------------------


class TestTreeSitterParser:
    """Test the unified tree-sitter parser."""

    def test_language_configs_defined(self):
        from attocode.integrations.context.ts_parser import LANGUAGE_CONFIGS

        # Should have configs for at least 8 languages
        assert len(LANGUAGE_CONFIGS) >= 8
        assert "python" in LANGUAGE_CONFIGS
        assert "go" in LANGUAGE_CONFIGS
        assert "rust" in LANGUAGE_CONFIGS
        assert "java" in LANGUAGE_CONFIGS
        assert "ruby" in LANGUAGE_CONFIGS
        assert "c" in LANGUAGE_CONFIGS
        assert "cpp" in LANGUAGE_CONFIGS

    def test_supported_languages(self):
        from attocode.integrations.context.ts_parser import supported_languages

        langs = supported_languages()
        assert "python" in langs
        assert "javascript" in langs
        assert "go" in langs

    def test_unsupported_language_returns_none(self):
        from attocode.integrations.context.ts_parser import ts_parse_file

        result = ts_parse_file("test.xyz", content="hello", language="xyz")
        assert result is None

    def test_parse_python_if_available(self):
        """Test tree-sitter Python parsing if the grammar is installed."""
        from attocode.integrations.context.ts_parser import is_available, ts_parse_file

        if not is_available("python"):
            pytest.skip("tree-sitter-python not installed")

        code = '''
def hello(name: str) -> str:
    """Greet someone."""
    return f"Hello, {name}!"

class Greeter:
    def greet(self, name):
        return hello(name)
'''
        result = ts_parse_file("test.py", content=code, language="python")
        assert result is not None
        assert len(result["functions"]) >= 1
        assert result["functions"][0]["name"] == "hello"
        assert len(result["classes"]) >= 1
        assert result["classes"][0]["name"] == "Greeter"

    def test_ts_result_to_file_ast(self):
        """Test conversion from tree-sitter result dict to FileAST."""
        from attocode.integrations.context.codebase_ast import _ts_result_to_file_ast

        result = {
            "language": "python",
            "functions": [
                {
                    "name": "foo",
                    "parameters": ["x", "y"],
                    "return_type": "int",
                    "start_line": 1,
                    "end_line": 5,
                    "is_async": False,
                    "decorators": [],
                    "visibility": "public",
                }
            ],
            "classes": [
                {
                    "name": "Bar",
                    "bases": ["Base"],
                    "methods": [
                        {
                            "name": "baz",
                            "parameters": ["self"],
                            "return_type": "",
                            "start_line": 8,
                            "end_line": 10,
                            "is_async": False,
                            "decorators": [],
                            "visibility": "public",
                        }
                    ],
                    "decorators": [],
                    "start_line": 7,
                    "end_line": 10,
                }
            ],
            "imports": [{"module": "os", "is_from": False}],
            "top_level_vars": ["MAX_SIZE"],
            "line_count": 10,
        }

        ast = _ts_result_to_file_ast(result, "test.py")
        assert ast.language == "python"
        assert len(ast.functions) == 1
        assert ast.functions[0].name == "foo"
        assert ast.functions[0].return_type == "int"
        assert len(ast.classes) == 1
        assert ast.classes[0].name == "Bar"
        assert len(ast.classes[0].methods) == 1
        assert ast.imports[0].module == "os"
        assert "MAX_SIZE" in ast.top_level_vars


# ---------------------------------------------------------------------------
# AST-aware chunking (P7)
# ---------------------------------------------------------------------------


class TestASTChunker:
    """Test AST-aware code chunking for semantic search."""

    def test_reciprocal_rank_fusion(self):
        from attocode.integrations.context.ast_chunker import reciprocal_rank_fusion

        list_a = [("doc1", 0.9), ("doc2", 0.8), ("doc3", 0.7)]
        list_b = [("doc2", 0.95), ("doc4", 0.85), ("doc1", 0.75)]

        merged = reciprocal_rank_fusion(list_a, list_b)

        # doc1 and doc2 appear in both lists, should rank highest
        ids = [item_id for item_id, _ in merged]
        assert "doc2" in ids[:2]  # doc2 is rank 1 in one, rank 2 in other
        assert "doc1" in ids[:3]

    def test_rrf_single_list(self):
        from attocode.integrations.context.ast_chunker import reciprocal_rank_fusion

        results = [("a", 1.0), ("b", 0.5)]
        merged = reciprocal_rank_fusion(results)
        assert merged[0][0] == "a"
        assert merged[1][0] == "b"

    def test_rrf_empty(self):
        from attocode.integrations.context.ast_chunker import reciprocal_rank_fusion

        merged = reciprocal_rank_fusion()
        assert merged == []

    def test_chunk_file_basic(self, tmp_path: Path):
        from attocode.integrations.context.ast_chunker import chunk_file

        code = '''"""Module docstring."""

import os

def hello(name: str) -> str:
    """Greet someone."""
    return f"Hello, {name}!"

class Greeter:
    """A greeter class."""
    def greet(self, name):
        return hello(name)
'''
        test_file = tmp_path / "test.py"
        test_file.write_text(code)

        chunks = chunk_file(str(test_file), "test.py")

        # Should have: 1 file + 1 function + 1 class + 1 method = 4 chunks
        chunk_types = [c.chunk_type for c in chunks]
        assert "file" in chunk_types
        assert "function" in chunk_types
        assert "class" in chunk_types

        # File chunk should contain actual code
        file_chunk = [c for c in chunks if c.chunk_type == "file"][0]
        assert "import os" in file_chunk.text

        # Function chunk should contain actual code
        func_chunks = [c for c in chunks if c.chunk_type == "function"]
        assert len(func_chunks) >= 1
        assert "hello" in func_chunks[0].name

    def test_chunk_file_nonexistent(self):
        from attocode.integrations.context.ast_chunker import chunk_file

        chunks = chunk_file("/nonexistent/file.py", "file.py")
        assert chunks == []


# ---------------------------------------------------------------------------
# Graph store (P8)
# ---------------------------------------------------------------------------


class TestGraphStore:
    """Test the persistent SQLite graph store."""

    def test_lifecycle(self, tmp_path: Path):
        from attocode.integrations.context.graph_store import CachedFileInfo, GraphStore

        store = GraphStore(
            project_dir=str(tmp_path),
            db_path=str(tmp_path / "test_graph.db"),
        )

        # Initially empty
        assert store.file_count == 0
        assert store.get_cached_files() == {}

        # Upsert a file
        info = CachedFileInfo(
            relative_path="src/main.py",
            content_hash="abc123",
            language="python",
            line_count=100,
            importance=0.8,
            mtime=1000.0,
        )
        store.upsert_file(info)
        store.commit()

        assert store.file_count == 1
        cached = store.get_cached_files()
        assert "src/main.py" in cached
        assert cached["src/main.py"].content_hash == "abc123"

        # Remove file
        store.remove_file("src/main.py")
        store.commit()
        assert store.file_count == 0

        store.close()

    def test_dependencies(self, tmp_path: Path):
        from attocode.integrations.context.graph_store import GraphStore

        store = GraphStore(
            project_dir=str(tmp_path),
            db_path=str(tmp_path / "test_deps.db"),
        )

        store.set_dependencies("a.py", ["b.py", "c.py"])
        store.set_dependencies("b.py", ["c.py"])
        store.commit()

        forward = store.get_forward_deps()
        assert forward["a.py"] == {"b.py", "c.py"}
        assert forward["b.py"] == {"c.py"}

        reverse = store.get_reverse_deps()
        assert "a.py" in reverse["b.py"]
        assert "a.py" in reverse["c.py"]
        assert "b.py" in reverse["c.py"]

        store.close()

    def test_symbols(self, tmp_path: Path):
        from attocode.integrations.context.graph_store import GraphStore

        store = GraphStore(
            project_dir=str(tmp_path),
            db_path=str(tmp_path / "test_sym.db"),
        )

        store.set_symbols("main.py", [
            {"name": "main", "qualified_name": "main", "kind": "function",
             "start_line": 1, "end_line": 10},
            {"name": "Config", "qualified_name": "Config", "kind": "class",
             "start_line": 12, "end_line": 30},
        ])
        store.commit()

        syms = store.get_symbols_for_file("main.py")
        assert len(syms) == 2
        assert syms[0]["name"] == "main"
        assert syms[1]["name"] == "Config"

        store.close()

    def test_diff_filesystem(self, tmp_path: Path):
        from attocode.integrations.context.graph_store import CachedFileInfo, GraphStore

        store = GraphStore(
            project_dir=str(tmp_path),
            db_path=str(tmp_path / "test_diff.db"),
        )

        # Cache two files
        store.upsert_file(CachedFileInfo("a.py", "hash_a", "python", 50, 0.5, 0))
        store.upsert_file(CachedFileInfo("b.py", "hash_b", "python", 30, 0.4, 0))
        store.commit()

        # Current filesystem: a.py changed, b.py same, c.py new
        current = {
            "a.py": "hash_a_new",  # modified
            "b.py": "hash_b",  # unchanged
            "c.py": "hash_c",  # new
        }

        added, modified, removed = store.diff_filesystem(current)
        assert added == ["c.py"]
        assert modified == ["a.py"]
        assert removed == []  # b.py still exists

        # Now remove b.py from current
        current.pop("b.py")
        added, modified, removed = store.diff_filesystem(current)
        assert "b.py" in removed

        store.close()

    def test_metadata(self, tmp_path: Path):
        from attocode.integrations.context.graph_store import GraphStore

        store = GraphStore(
            project_dir=str(tmp_path),
            db_path=str(tmp_path / "test_meta.db"),
        )

        assert store.get_meta("version") is None
        store.set_meta("version", "1.0")
        store.commit()
        assert store.get_meta("version") == "1.0"

        store.close()

    def test_clear(self, tmp_path: Path):
        from attocode.integrations.context.graph_store import CachedFileInfo, GraphStore

        store = GraphStore(
            project_dir=str(tmp_path),
            db_path=str(tmp_path / "test_clear.db"),
        )

        store.upsert_file(CachedFileInfo("x.py", "h", "py", 10, 0.5, 0))
        store.set_dependencies("x.py", ["y.py"])
        store.set_symbols("x.py", [{"name": "f", "kind": "function"}])
        store.commit()

        assert store.file_count == 1

        store.clear()
        assert store.file_count == 0
        assert store.get_forward_deps() == {}
        assert store.get_symbols_for_file("x.py") == []

        store.close()


# ---------------------------------------------------------------------------
# File watcher (P6)
# ---------------------------------------------------------------------------


class TestFileWatcher:
    """Test file watcher setup/teardown."""

    def test_watcher_graceful_without_watchfiles(self, monkeypatch: pytest.MonkeyPatch):
        """File watcher should not crash when watchfiles is not installed."""
        import attocode.code_intel.server as srv

        # Force import error
        original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

        def mock_import(name, *args, **kwargs):
            if name == "watchfiles":
                raise ImportError("mocked")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", mock_import)

        # Should not raise
        srv._start_file_watcher("/tmp/test")
        assert srv._watcher_thread is None

    def test_watcher_stop_without_start(self):
        """Stopping without starting should not crash."""
        import attocode.code_intel.server as srv

        srv._watcher_thread = None
        srv._stop_file_watcher()
        assert srv._watcher_thread is None


# ---------------------------------------------------------------------------
# GUIDELINES.md resource (P1)
# ---------------------------------------------------------------------------


class TestGuidelinesResource:
    """Test that GUIDELINES.md exists and is exposed as MCP resource."""

    def test_guidelines_file_exists(self):
        from pathlib import Path

        guidelines = Path(__file__).parent.parent.parent / "src" / "attocode" / "code_intel" / "GUIDELINES.md"
        assert guidelines.exists(), f"GUIDELINES.md not found at {guidelines}"

    def test_guidelines_contains_tool_inventory(self):
        from pathlib import Path

        guidelines = Path(__file__).parent.parent.parent / "src" / "attocode" / "code_intel" / "GUIDELINES.md"
        content = guidelines.read_text()
        assert "Tool Inventory" in content
        assert "bootstrap" in content
        assert "relevant_context" in content
        assert "Progressive Disclosure" in content

    def test_guidelines_resource_function(self, monkeypatch: pytest.MonkeyPatch):
        from attocode.code_intel.server import guidelines_resource

        result = guidelines_resource()
        assert isinstance(result, str)
        assert len(result) > 100
        assert "Tool Inventory" in result

    def test_guidelines_contains_index_freshness(self):
        from pathlib import Path

        guidelines = Path(__file__).parent.parent.parent / "src" / "attocode" / "code_intel" / "GUIDELINES.md"
        content = guidelines.read_text()
        assert "Keeping the Index Fresh" in content
        assert "notify_file_changed" in content


# ---------------------------------------------------------------------------
# notify_file_changed MCP tool
# ---------------------------------------------------------------------------


class TestNotifyFileChanged:
    """Test the notify_file_changed MCP tool."""

    @pytest.fixture(autouse=True)
    def _setup_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ATTOCODE_PROJECT_DIR", str(tmp_path))
        self.tmp_path = tmp_path

        import attocode.code_intel.server as srv

        srv._ast_service = None
        srv._context_mgr = None
        srv._code_analyzer = None
        srv._semantic_search = None
        yield
        srv._ast_service = None
        srv._context_mgr = None
        srv._code_analyzer = None
        srv._semantic_search = None

    def test_notify_empty_list(self):
        from attocode.code_intel.server import notify_file_changed

        result = notify_file_changed([])
        assert result == "No files specified."

    def test_notify_updates_ast_and_embeddings(self):
        import attocode.code_intel.server as srv
        from attocode.code_intel.server import notify_file_changed

        mock_svc = MagicMock()
        mock_svc.initialized = True
        srv._ast_service = mock_svc

        mock_smgr = MagicMock()
        srv._semantic_search = mock_smgr

        result = notify_file_changed(["src/foo.py", "src/bar.py"])

        assert "2 file(s)" in result
        assert mock_svc.notify_file_changed.call_count == 2
        assert mock_smgr.invalidate_file.call_count == 2

    def test_notify_handles_absolute_paths(self):
        import attocode.code_intel.server as srv
        from attocode.code_intel.server import notify_file_changed

        mock_svc = MagicMock()
        mock_svc.initialized = True
        srv._ast_service = mock_svc

        mock_smgr = MagicMock()
        srv._semantic_search = mock_smgr

        abs_path = str(self.tmp_path / "src" / "test.py")
        result = notify_file_changed([abs_path])

        assert "1 file(s)" in result
        # Should have been converted to relative path
        call_arg = mock_svc.notify_file_changed.call_args[0][0]
        assert not call_arg.startswith("/")

    def test_notify_resilient_to_errors(self):
        import attocode.code_intel.server as srv
        from attocode.code_intel.server import notify_file_changed

        mock_svc = MagicMock()
        mock_svc.initialized = True
        mock_svc.notify_file_changed.side_effect = [None, RuntimeError("boom")]
        srv._ast_service = mock_svc

        mock_smgr = MagicMock()
        srv._semantic_search = mock_smgr

        result = notify_file_changed(["good.py", "bad.py"])
        # Should still report 1 success (the first one)
        assert "1 file(s)" in result


# ---------------------------------------------------------------------------
# Notification queue
# ---------------------------------------------------------------------------


class TestNotificationQueue:
    """Test the notification queue processing."""

    @pytest.fixture(autouse=True)
    def _setup_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ATTOCODE_PROJECT_DIR", str(tmp_path))
        self.tmp_path = tmp_path

        import attocode.code_intel.server as srv

        srv._ast_service = None
        srv._context_mgr = None
        srv._code_analyzer = None
        srv._semantic_search = None
        yield
        srv._ast_service = None
        srv._context_mgr = None
        srv._code_analyzer = None
        srv._semantic_search = None

    def test_empty_queue(self):
        from attocode.code_intel.server import _process_notification_queue

        result = _process_notification_queue()
        assert result == 0

    def test_process_queued_files(self):
        import attocode.code_intel.server as srv
        from attocode.code_intel.server import _process_notification_queue

        mock_svc = MagicMock()
        mock_svc.initialized = True
        srv._ast_service = mock_svc

        mock_smgr = MagicMock()
        srv._semantic_search = mock_smgr

        # Write queue file
        queue_path = self.tmp_path / ".attocode" / "cache" / "file_changes"
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        queue_path.write_text("src/a.py\nsrc/b.py\n", encoding="utf-8")

        result = _process_notification_queue()
        assert result == 2
        assert mock_svc.notify_file_changed.call_count == 2
        assert mock_smgr.invalidate_file.call_count == 2

        # Queue should be truncated
        assert queue_path.read_text() == ""

    def test_queue_skips_blank_lines(self):
        import attocode.code_intel.server as srv
        from attocode.code_intel.server import _process_notification_queue

        mock_svc = MagicMock()
        mock_svc.initialized = True
        srv._ast_service = mock_svc
        srv._semantic_search = MagicMock()

        queue_path = self.tmp_path / ".attocode" / "cache" / "file_changes"
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        queue_path.write_text("\n\nsrc/a.py\n\n", encoding="utf-8")

        result = _process_notification_queue()
        assert result == 1


# ---------------------------------------------------------------------------
# Install hooks
# ---------------------------------------------------------------------------


class TestInstallHooks:
    """Test hook installation for Claude Code."""

    def test_install_hooks_claude(self, tmp_path: Path):
        from attocode.code_intel.installer import install_hooks

        result = install_hooks("claude", project_dir=str(tmp_path))
        assert result is True

        settings_path = tmp_path / ".claude" / "settings.local.json"
        assert settings_path.exists()

        data = json.loads(settings_path.read_text())
        hooks = data["hooks"]["PostToolUse"]
        assert len(hooks) == 1
        assert hooks[0]["matcher"] == "Edit|Write|NotebookEdit"
        assert hooks[0]["hooks"][0]["command"] == "attocode-code-intel notify --stdin"

    def test_install_hooks_idempotent(self, tmp_path: Path):
        from attocode.code_intel.installer import install_hooks

        install_hooks("claude", project_dir=str(tmp_path))
        install_hooks("claude", project_dir=str(tmp_path))

        settings_path = tmp_path / ".claude" / "settings.local.json"
        data = json.loads(settings_path.read_text())
        hooks = data["hooks"]["PostToolUse"]
        assert len(hooks) == 1  # Not duplicated

    def test_install_hooks_preserves_existing(self, tmp_path: Path):
        from attocode.code_intel.installer import install_hooks

        settings_path = tmp_path / ".claude" / "settings.local.json"
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps({
            "existing_key": "value",
            "hooks": {
                "PostToolUse": [
                    {"matcher": {"tool_name": "Bash"}, "hooks": [{"type": "command", "command": "echo hi"}]}
                ]
            }
        }))

        install_hooks("claude", project_dir=str(tmp_path))

        data = json.loads(settings_path.read_text())
        assert data["existing_key"] == "value"
        assert len(data["hooks"]["PostToolUse"]) == 2  # Existing + ours

    def test_install_hooks_unsupported_target(self, tmp_path: Path, capsys):
        from attocode.code_intel.installer import install_hooks

        result = install_hooks("cursor", project_dir=str(tmp_path))
        assert result is False
        captured = capsys.readouterr()
        assert "not supported" in captured.out.lower()

    def test_uninstall_hooks_claude(self, tmp_path: Path):
        from attocode.code_intel.installer import install_hooks, uninstall_hooks

        install_hooks("claude", project_dir=str(tmp_path))
        result = uninstall_hooks("claude", project_dir=str(tmp_path))
        assert result is True

        settings_path = tmp_path / ".claude" / "settings.local.json"
        data = json.loads(settings_path.read_text())
        assert len(data["hooks"]["PostToolUse"]) == 0

    def test_uninstall_hooks_no_file(self, tmp_path: Path):
        from attocode.code_intel.installer import uninstall_hooks

        result = uninstall_hooks("claude", project_dir=str(tmp_path))
        assert result is True

    def test_install_hooks_upgrades_old_format(self, tmp_path: Path):
        """Reinstall should replace old dict-matcher hook, not duplicate."""
        from attocode.code_intel.installer import install_hooks

        settings_path = tmp_path / ".claude" / "settings.local.json"
        settings_path.parent.mkdir(parents=True, exist_ok=True)

        # Old format: dict matcher + jq/xargs command
        old_hook = {
            "matcher": {"tool_name": "Edit|Write|NotebookEdit"},
            "hooks": [
                {
                    "type": "command",
                    "command": "jq -r .tool_input.file_path | xargs attocode-code-intel notify",
                }
            ],
        }
        settings_path.write_text(json.dumps({
            "hooks": {"PostToolUse": [old_hook]}
        }))

        result = install_hooks("claude", project_dir=str(tmp_path))
        assert result is True

        data = json.loads(settings_path.read_text())
        hooks = data["hooks"]["PostToolUse"]
        assert len(hooks) == 1  # Replaced, not duplicated
        assert hooks[0]["matcher"] == "Edit|Write|NotebookEdit"  # String, not dict
        assert hooks[0]["hooks"][0]["command"] == "attocode-code-intel notify --stdin"


# ---------------------------------------------------------------------------
# CLI notify subcommand
# ---------------------------------------------------------------------------


class TestNotifyCLI:
    """Test the CLI notify subcommand."""

    def test_notify_with_file_flag(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from attocode.code_intel.cli import _cmd_notify

        monkeypatch.setenv("ATTOCODE_PROJECT_DIR", str(tmp_path))

        _cmd_notify(["--project", str(tmp_path), "--file", "src/foo.py"])

        queue_path = tmp_path / ".attocode" / "cache" / "file_changes"
        assert queue_path.exists()
        content = queue_path.read_text()
        assert "src/foo.py" in content

    def test_notify_multiple_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from attocode.code_intel.cli import _cmd_notify

        monkeypatch.setenv("ATTOCODE_PROJECT_DIR", str(tmp_path))

        _cmd_notify(["--project", str(tmp_path), "--file", "a.py", "--file", "b.py"])

        queue_path = tmp_path / ".attocode" / "cache" / "file_changes"
        content = queue_path.read_text()
        assert "a.py" in content
        assert "b.py" in content

    def test_notify_no_files_exits(self, monkeypatch: pytest.MonkeyPatch):
        from attocode.code_intel.cli import _cmd_notify

        monkeypatch.setenv("ATTOCODE_PROJECT_DIR", "/tmp/test")

        with pytest.raises(SystemExit):
            _cmd_notify(["--project", "/tmp/test"])

    def test_notify_stdin_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """--stdin should parse JSON with tool_input.file_path from Claude Code hooks."""
        import io
        from attocode.code_intel.cli import _cmd_notify

        monkeypatch.setenv("ATTOCODE_PROJECT_DIR", str(tmp_path))

        json_payload = '{"tool_name":"Edit","tool_input":{"file_path":"src/edited.py","old_string":"a","new_string":"b"}}\n'
        monkeypatch.setattr("sys.stdin", io.StringIO(json_payload))

        _cmd_notify(["--project", str(tmp_path), "--stdin"])

        queue_path = tmp_path / ".attocode" / "cache" / "file_changes"
        content = queue_path.read_text()
        assert "src/edited.py" in content

    def test_notify_stdin_plain_lines(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """--stdin should also accept plain file paths (one per line)."""
        import io
        from attocode.code_intel.cli import _cmd_notify

        monkeypatch.setenv("ATTOCODE_PROJECT_DIR", str(tmp_path))

        monkeypatch.setattr("sys.stdin", io.StringIO("src/a.py\nsrc/b.py\n"))

        _cmd_notify(["--project", str(tmp_path), "--stdin"])

        queue_path = tmp_path / ".attocode" / "cache" / "file_changes"
        content = queue_path.read_text()
        assert "src/a.py" in content
        assert "src/b.py" in content

    def test_parse_opts_hooks_flag(self):
        from attocode.code_intel.cli import _parse_opts

        target, project_dir, scope, hooks = _parse_opts(["claude", "--hooks"])
        assert target == "claude"
        assert hooks is True

        target2, _, _, hooks2 = _parse_opts(["cursor"])
        assert target2 == "cursor"
        assert hooks2 is False


# ---------------------------------------------------------------------------
# Path traversal guard
# ---------------------------------------------------------------------------


class TestPathTraversalGuard:
    """Ensure ../paths are rejected by the notification system."""

    @pytest.fixture(autouse=True)
    def _setup_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ATTOCODE_PROJECT_DIR", str(tmp_path))
        self.tmp_path = tmp_path

        import attocode.code_intel.server as srv

        srv._ast_service = None
        srv._context_mgr = None
        srv._code_analyzer = None
        srv._semantic_search = None
        yield
        srv._ast_service = None
        srv._context_mgr = None
        srv._code_analyzer = None
        srv._semantic_search = None

    def test_notify_rejects_traversal_path(self):
        import attocode.code_intel.server as srv
        from attocode.code_intel.server import notify_file_changed

        mock_svc = MagicMock()
        mock_svc.initialized = True
        srv._ast_service = mock_svc
        srv._semantic_search = MagicMock()

        result = notify_file_changed(["../../etc/passwd", "src/ok.py"])

        # Only the safe path should be processed
        assert "1 file(s)" in result
        call_arg = mock_svc.notify_file_changed.call_args[0][0]
        assert "passwd" not in call_arg

    def test_queue_rejects_traversal_path(self):
        import attocode.code_intel.server as srv
        from attocode.code_intel.server import _process_notification_queue

        mock_svc = MagicMock()
        mock_svc.initialized = True
        srv._ast_service = mock_svc
        srv._semantic_search = MagicMock()

        queue_path = self.tmp_path / ".attocode" / "cache" / "file_changes"
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        queue_path.write_text("../../etc/passwd\nsrc/safe.py\n", encoding="utf-8")

        result = _process_notification_queue()
        assert result == 1
        call_arg = mock_svc.notify_file_changed.call_args[0][0]
        assert call_arg == "src/safe.py"


# ---------------------------------------------------------------------------
# Queue poller lifecycle
# ---------------------------------------------------------------------------


class TestQueuePoller:
    """Test the background queue poller thread lifecycle."""

    def test_start_queue_poller(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        import attocode.code_intel.server as srv

        monkeypatch.setenv("ATTOCODE_PROJECT_DIR", str(tmp_path))

        # Reset state
        srv._queue_thread = None
        srv._watcher_stop.clear()

        srv._start_queue_poller(str(tmp_path))
        assert srv._queue_thread is not None
        assert srv._queue_thread.is_alive()

        # Idempotent — second call is a no-op
        first_thread = srv._queue_thread
        srv._start_queue_poller(str(tmp_path))
        assert srv._queue_thread is first_thread

        # Clean up
        srv._watcher_stop.set()
        srv._queue_thread.join(timeout=5.0)
        srv._queue_thread = None
        srv._watcher_stop.clear()

    def test_stop_joins_queue_thread(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        import attocode.code_intel.server as srv

        monkeypatch.setenv("ATTOCODE_PROJECT_DIR", str(tmp_path))

        srv._queue_thread = None
        srv._watcher_thread = None
        srv._watcher_stop.clear()

        srv._start_queue_poller(str(tmp_path))
        assert srv._queue_thread is not None

        srv._stop_file_watcher()
        assert srv._queue_thread is None
        assert srv._watcher_stop.is_set()

        # Reset for other tests
        srv._watcher_stop.clear()


# ---------------------------------------------------------------------------
# Memory / Recall MCP tool tests
# ---------------------------------------------------------------------------


class TestMemoryTools:
    """Test the memory/recall MCP tools."""

    @pytest.fixture(autouse=True)
    def _setup_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Set up project dir and reset memory store singleton."""
        monkeypatch.setenv("ATTOCODE_PROJECT_DIR", str(tmp_path))
        import attocode.code_intel.server as srv

        srv._memory_store = None
        yield
        if srv._memory_store is not None:
            srv._memory_store.close()
            srv._memory_store = None

    def test_recall_empty(self):
        from attocode.code_intel.server import recall

        result = recall("anything")
        assert "No relevant learnings" in result

    def test_record_and_recall(self):
        from attocode.code_intel.server import recall, record_learning

        result = record_learning(
            type="convention",
            description="Always use snake_case for function names",
        )
        assert "Recorded learning #" in result
        assert "convention" in result

        recalled = recall("function naming")
        assert "snake_case" in recalled
        assert "convention" in recalled

    def test_record_invalid_type(self):
        from attocode.code_intel.server import record_learning

        result = record_learning(type="invalid", description="test")
        assert "Error" in result

    def test_learning_feedback_helpful(self):
        from attocode.code_intel.server import learning_feedback, record_learning

        record_learning(type="pattern", description="Cache DB queries for speed")
        result = learning_feedback(learning_id=1, helpful=True)
        assert "boosted" in result

    def test_learning_feedback_unhelpful(self):
        from attocode.code_intel.server import learning_feedback, record_learning

        record_learning(type="gotcha", description="Watch out for race conditions")
        result = learning_feedback(learning_id=1, helpful=False)
        assert "reduced" in result

    def test_list_learnings_empty(self):
        from attocode.code_intel.server import list_learnings

        result = list_learnings()
        assert "No learnings found" in result

    def test_list_learnings_with_data(self):
        from attocode.code_intel.server import list_learnings, record_learning

        record_learning(type="pattern", description="Use dataclass slots")
        record_learning(type="gotcha", description="FTS5 quoting rules")

        result = list_learnings()
        assert "dataclass" in result
        assert "FTS5" in result
        assert "| ID |" in result  # Table header

    def test_list_learnings_type_filter(self):
        from attocode.code_intel.server import list_learnings, record_learning

        record_learning(type="pattern", description="Pattern learning")
        record_learning(type="gotcha", description="Gotcha learning")

        result = list_learnings(type="pattern")
        assert "Pattern learning" in result
        assert "Gotcha learning" not in result

    def test_learnings_resource(self):
        from attocode.code_intel.server import learnings_resource, record_learning

        # Empty
        result = learnings_resource()
        assert "No project learnings" in result

        # With data
        record_learning(type="convention", description="Use type hints everywhere")
        result = learnings_resource()
        assert "Convention" in result
        assert "type hints" in result

    def test_record_with_scope_and_details(self):
        from attocode.code_intel.server import recall, record_learning

        record_learning(
            type="workaround",
            description="Mock the DB in integration tests",
            details="Use monkeypatch to swap the connection factory",
            scope="tests/integration/",
        )

        result = recall("database mocking", scope="tests/integration/")
        assert "Mock the DB" in result

    def test_list_learnings_scope_filter(self):
        from attocode.code_intel.server import list_learnings, record_learning

        record_learning(type="pattern", description="Scoped learning", scope="src/api/")
        record_learning(type="pattern", description="Global learning", scope="")

        result = list_learnings(scope="src/api/")
        assert "Scoped learning" in result
        assert "Global learning" in result  # Global is always included


# ============================================================
# Community Detection (Louvain) Tests
# ============================================================


class TestCommunityDetection:
    """Test Louvain community detection with graceful BFS fallback."""

    def test_louvain_separates_clusters(self) -> None:
        """Three distinct clusters should be correctly found by Louvain."""
        try:
            import networkx as nx
            from networkx.algorithms.community import louvain_communities, modularity
        except ImportError:
            pytest.skip("networkx not installed")

        # Build 3 distinct clusters connected by a single bridge each
        all_files = set()
        adj: dict[str, set[str]] = {}
        weights: dict[tuple[str, str], float] = {}

        # Cluster A: a1-a5 fully connected
        for i in range(1, 6):
            f = f"a{i}.py"
            all_files.add(f)
            adj.setdefault(f, set())
        for i in range(1, 6):
            for j in range(i + 1, 6):
                src, tgt = f"a{i}.py", f"a{j}.py"
                adj[src].add(tgt)
                adj[tgt].add(src)
                weights[(src, tgt)] = 2.0

        # Cluster B: b1-b5 fully connected
        for i in range(1, 6):
            f = f"b{i}.py"
            all_files.add(f)
            adj.setdefault(f, set())
        for i in range(1, 6):
            for j in range(i + 1, 6):
                src, tgt = f"b{i}.py", f"b{j}.py"
                adj[src].add(tgt)
                adj[tgt].add(src)
                weights[(src, tgt)] = 2.0

        # Cluster C: c1-c5 fully connected
        for i in range(1, 6):
            f = f"c{i}.py"
            all_files.add(f)
            adj.setdefault(f, set())
        for i in range(1, 6):
            for j in range(i + 1, 6):
                src, tgt = f"c{i}.py", f"c{j}.py"
                adj[src].add(tgt)
                adj[tgt].add(src)
                weights[(src, tgt)] = 2.0

        # Weak bridges
        adj["a1.py"].add("b1.py")
        adj["b1.py"].add("a1.py")
        weights[("a1.py", "b1.py")] = 1.0
        adj["b1.py"].add("c1.py")
        adj["c1.py"].add("b1.py")
        weights[("b1.py", "c1.py")] = 1.0

        # Build networkx graph and run Louvain
        G = nx.Graph()
        G.add_nodes_from(all_files)
        for src, neighbors in adj.items():
            for tgt in neighbors:
                if src < tgt:
                    w = weights.get((src, tgt), weights.get((tgt, src), 1.0))
                    G.add_edge(src, tgt, weight=w)

        communities = [set(c) for c in louvain_communities(G, weight="weight", seed=42)]
        assert len(communities) >= 3, f"Expected >=3 communities, got {len(communities)}"

    def test_fallback_without_networkx(self) -> None:
        """BFS fallback should work as connected components."""
        from collections import deque as _deque

        all_files = {"a.py", "b.py", "c.py", "d.py"}
        adj: dict[str, set[str]] = {
            "a.py": {"b.py"},
            "b.py": {"a.py"},
            "c.py": {"d.py"},
            "d.py": {"c.py"},
        }

        # Inline BFS connected components (same algo as the fallback)
        visited: set[str] = set()
        communities: list[set[str]] = []
        for start in all_files:
            if start in visited:
                continue
            component: set[str] = set()
            bfs_queue: _deque[str] = _deque([start])
            while bfs_queue:
                node = bfs_queue.popleft()
                if node in visited:
                    continue
                visited.add(node)
                component.add(node)
                for neighbor in adj.get(node, set()):
                    if neighbor not in visited:
                        bfs_queue.append(neighbor)
            communities.append(component)

        assert len(communities) == 2

    def test_modularity_positive(self) -> None:
        """Non-trivial graph with clear clusters should have positive modularity."""
        try:
            import networkx as nx
            from networkx.algorithms.community import louvain_communities, modularity
        except ImportError:
            pytest.skip("networkx not installed")

        all_files = set()
        adj: dict[str, set[str]] = {}
        weights: dict[tuple[str, str], float] = {}

        # Two fully-connected clusters of 4 nodes each, with one weak bridge
        for prefix in ("x", "y"):
            for i in range(1, 5):
                f = f"{prefix}{i}.py"
                all_files.add(f)
                adj.setdefault(f, set())
            for i in range(1, 5):
                for j in range(i + 1, 5):
                    src, tgt = f"{prefix}{i}.py", f"{prefix}{j}.py"
                    adj[src].add(tgt)
                    adj[tgt].add(src)
                    weights[(src, tgt)] = 2.0

        # Weak bridge
        adj["x1.py"].add("y1.py")
        adj["y1.py"].add("x1.py")
        weights[("x1.py", "y1.py")] = 1.0

        G = nx.Graph()
        G.add_nodes_from(all_files)
        for src, neighbors in adj.items():
            for tgt in neighbors:
                if src < tgt:
                    w = weights.get((src, tgt), weights.get((tgt, src), 1.0))
                    G.add_edge(src, tgt, weight=w)

        communities = [set(c) for c in louvain_communities(G, weight="weight", seed=42)]
        mod_score = modularity(G, communities, weight="weight")
        assert mod_score > 0, f"Expected positive modularity, got {mod_score}"

    def test_empty_graph_no_edges(self) -> None:
        """Community detection on a graph with no edges should not raise."""
        from attocode.code_intel.community import louvain_communities as _louvain

        try:
            import networkx  # noqa: F401
        except ImportError:
            pytest.skip("networkx not installed")

        all_files = {"a.py", "b.py", "c.py"}
        adj: dict[str, set[str]] = {f: set() for f in all_files}
        weights: dict[tuple[str, str], float] = {}

        communities, modularity_score = _louvain(all_files, adj, weights)
        # Each file should be its own community
        assert len(communities) == 3
        assert modularity_score == 0.0
        # All files accounted for
        all_nodes = set()
        for c in communities:
            all_nodes.update(c)
        assert all_nodes == all_files
