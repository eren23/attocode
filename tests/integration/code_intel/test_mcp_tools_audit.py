"""Comprehensive audit of all 43 MCP code-intel tools.

Imports each tool function directly and calls it with mocked singletons.
Catches AttributeError / TypeError / KeyError crashes that indicate
broken method calls or missing attributes on shared objects.

Run:
    pytest tests/integration/code_intel/test_mcp_tools_audit.py -v --tb=long
"""

from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

# ---------------------------------------------------------------------------
# Domain types used by the mock factory
# ---------------------------------------------------------------------------

from attocode.integrations.context.codebase_context import (
    DependencyGraph,
    FileInfo,
    RepoMap,
)
from attocode.integrations.context.cross_references import (
    CrossRefIndex,
    SymbolLocation,
    SymbolRef,
)
from attocode.integrations.context.codebase_ast import (
    FileAST,
    FunctionDef,
    ClassDef,
    ImportDef,
    ParamDef,
)


# ---------------------------------------------------------------------------
# Mock factory
# ---------------------------------------------------------------------------


def _build_audit_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Build realistic mock singletons covering all 43 MCP tools."""
    import attocode.code_intel.server as srv

    project_dir = str(tmp_path)
    monkeypatch.setenv("ATTOCODE_PROJECT_DIR", project_dir)

    # Reset all singletons
    srv._ast_service = None
    srv._context_mgr = None
    srv._code_analyzer = None
    srv._memory_store = None
    srv._explorer = None

    # Create real files so file_analysis and others can read them
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "main.py").write_text(
        "import os\nfrom src.utils import helper\n\ndef main():\n    helper(42)\n\ndef cli(args: list[str]) -> int:\n    return 0\n"
    )
    (tmp_path / "src" / "utils.py").write_text(
        "import os\n\ndef helper(value: int) -> str:\n    return str(value)\n\ndef _parse_data(raw):\n    pass\n\nclass BaseProcessor:\n    def process(self) -> None: ...\n"
    )
    (tmp_path / "tests" / "test_main.py").write_text(
        "import pytest\n\ndef test_basic(): pass\ndef test_advanced(): pass\n"
    )
    (tmp_path / "tests" / "test_utils.py").write_text(
        "import pytest\n\ndef test_helper(): pass\n"
    )
    (tmp_path / "tests" / "test_edge.py").write_text(
        "import pytest\n\ndef test_empty(): pass\n"
    )
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "audit-project"\nversion = "0.1.0"\n'
    )

    # --- FileInfo objects ---
    files = [
        FileInfo(path=str(tmp_path / "src/main.py"), relative_path="src/main.py",
                 size=5000, language="python", importance=0.9, line_count=200),
        FileInfo(path=str(tmp_path / "src/utils.py"), relative_path="src/utils.py",
                 size=15000, language="python", importance=0.7, line_count=600),
        FileInfo(path=str(tmp_path / "tests/test_main.py"), relative_path="tests/test_main.py",
                 size=3000, language="python", importance=0.3, is_test=True, line_count=80),
        FileInfo(path=str(tmp_path / "tests/test_utils.py"), relative_path="tests/test_utils.py",
                 size=2000, language="python", importance=0.2, is_test=True, line_count=60),
        FileInfo(path=str(tmp_path / "tests/test_edge.py"), relative_path="tests/test_edge.py",
                 size=1500, language="python", importance=0.2, is_test=True, line_count=50),
        FileInfo(path=str(tmp_path / "pyproject.toml"), relative_path="pyproject.toml",
                 size=500, language="toml", importance=0.1, is_config=True, line_count=30),
    ]

    # --- RepoMap ---
    repo_map = RepoMap(
        tree="src/\n  main.py\n  utils.py\ntests/\n  test_main.py\n  test_utils.py\n  test_edge.py",
        files=files, total_files=6, total_lines=1020,
        languages={"python": 5, "toml": 1},
    )

    # --- DependencyGraph ---
    dep_graph = DependencyGraph()
    dep_graph.add_edge("src/main.py", "src/utils.py")
    dep_graph.add_edge("tests/test_main.py", "src/main.py")
    dep_graph.add_edge("tests/test_main.py", "src/utils.py")

    # --- CrossRefIndex ---
    index = CrossRefIndex(
        definitions={
            "main": [SymbolLocation(name="main", qualified_name="main", kind="function",
                                    file_path="src/main.py", start_line=4, end_line=5)],
            "cli": [SymbolLocation(name="cli", qualified_name="cli", kind="function",
                                   file_path="src/main.py", start_line=7, end_line=8)],
            "helper": [SymbolLocation(name="helper", qualified_name="helper", kind="function",
                                      file_path="src/utils.py", start_line=3, end_line=4)],
            "BaseProcessor": [SymbolLocation(name="BaseProcessor", qualified_name="BaseProcessor",
                                             kind="class", file_path="src/utils.py",
                                             start_line=9, end_line=10)],
        },
        references={
            "helper": [SymbolRef(symbol_name="helper", ref_kind="call",
                                 file_path="src/main.py", line=5)],
            "main": [SymbolRef(symbol_name="main", ref_kind="call",
                               file_path="tests/test_main.py", line=3)],
        },
        file_dependents={
            "src/utils.py": {"src/main.py", "tests/test_main.py"},
            "src/main.py": {"tests/test_main.py"},
        },
        file_dependencies={
            "src/main.py": {"src/utils.py"},
            "tests/test_main.py": {"src/main.py", "src/utils.py"},
        },
        file_symbols={
            "src/main.py": {"main", "cli"},
            "src/utils.py": {"helper", "_parse_data", "BaseProcessor"},
        },
    )

    # --- FileAST entries ---
    main_ast = FileAST(
        path="src/main.py", language="python",
        functions=[
            FunctionDef(name="main", start_line=4, end_line=5, return_type="None",
                        parameters=[], docstring="Entry point."),
            FunctionDef(name="cli", start_line=7, end_line=8, return_type="int",
                        parameters=[ParamDef(name="args", type_annotation="list[str]")],
                        is_async=True, docstring="Parse CLI args."),
        ],
        classes=[],
        imports=[
            ImportDef(module="os", is_from=False, line=1),
            ImportDef(module="src.utils", names=["helper"], is_from=True, line=2),
        ],
        top_level_vars=["__all__"],
        line_count=200,
    )

    utils_ast = FileAST(
        path="src/utils.py", language="python",
        functions=[
            FunctionDef(name="helper", start_line=3, end_line=4, return_type="str",
                        parameters=[ParamDef(name="value", type_annotation="int")],
                        docstring="A helper function."),
            FunctionDef(name="_parse_data", start_line=6, end_line=7,
                        parameters=[ParamDef(name="raw")], visibility="private"),
        ],
        classes=[
            ClassDef(name="BaseProcessor", start_line=9, end_line=10, bases=[],
                     docstring="Base processor class.",
                     methods=[
                         FunctionDef(name="process", start_line=10, end_line=10,
                                     is_method=True, return_type="None",
                                     parameters=[ParamDef(name="self")]),
                     ]),
        ],
        imports=[ImportDef(module="os", is_from=False, line=1)],
        line_count=600,
    )

    test_ast = FileAST(
        path="tests/test_main.py", language="python",
        functions=[
            FunctionDef(name="test_basic", start_line=3, end_line=3, parameters=[]),
            FunctionDef(name="test_advanced", start_line=4, end_line=4, parameters=[]),
        ],
        classes=[], imports=[ImportDef(module="pytest", is_from=False, line=1)],
        line_count=80,
    )

    test_utils_ast = FileAST(
        path="tests/test_utils.py", language="python",
        functions=[FunctionDef(name="test_helper", start_line=3, end_line=3, parameters=[])],
        classes=[], imports=[ImportDef(module="pytest", is_from=False, line=1)],
        line_count=60,
    )

    test_edge_ast = FileAST(
        path="tests/test_edge.py", language="python",
        functions=[FunctionDef(name="test_empty", start_line=3, end_line=3, parameters=[])],
        classes=[], imports=[ImportDef(module="pytest", is_from=False, line=1)],
        line_count=50,
    )

    ast_cache = {
        "src/main.py": main_ast,
        "src/utils.py": utils_ast,
        "tests/test_main.py": test_ast,
        "tests/test_utils.py": test_utils_ast,
        "tests/test_edge.py": test_edge_ast,
    }

    # --- Wire ASTService mock ---
    svc_mock = MagicMock()
    svc_mock._index = index
    svc_mock.index = index  # public property equivalent
    svc_mock._ast_cache = ast_cache
    svc_mock.initialized = True
    svc_mock._to_rel = lambda path: os.path.relpath(path, project_dir) if os.path.isabs(path) else path
    svc_mock.get_file_symbols.return_value = [
        SymbolLocation(name="main", qualified_name="main", kind="function",
                       file_path="src/main.py", start_line=4, end_line=5),
        SymbolLocation(name="cli", qualified_name="cli", kind="function",
                       file_path="src/main.py", start_line=7, end_line=8),
    ]
    svc_mock.find_symbol.return_value = [
        SymbolLocation(name="helper", qualified_name="helper", kind="function",
                       file_path="src/utils.py", start_line=3, end_line=4),
    ]
    svc_mock.search_symbol.return_value = [
        (SymbolLocation(name="helper", qualified_name="helper", kind="function",
                        file_path="src/utils.py", start_line=3, end_line=4), 0.95),
    ]
    svc_mock.get_callers.return_value = [
        SymbolRef(symbol_name="helper", ref_kind="call", file_path="src/main.py", line=5),
    ]
    svc_mock.get_dependencies.return_value = ["src/utils.py"]
    svc_mock.get_dependents.return_value = ["tests/test_main.py"]
    svc_mock.get_impact.return_value = {"src/main.py", "tests/test_main.py"}
    svc_mock.force_reindex.return_value = None
    svc_mock.initialize.return_value = None
    svc_mock.notify_file_changed.return_value = None
    # _store mock for reindex / semantic_search_status
    store_mock = MagicMock()
    store_mock.stats.return_value = {"files": 6, "symbols": 50, "references": 20}
    svc_mock._store = store_mock

    # --- Wire CodebaseContextManager mock ---
    ctx_mock = MagicMock()
    ctx_mock._files = files
    ctx_mock.root_dir = project_dir
    ctx_mock._dep_graph = dep_graph
    # Make dependency_graph property work
    type(ctx_mock).dependency_graph = PropertyMock(return_value=dep_graph)
    ctx_mock.get_repo_map.return_value = repo_map
    ctx_mock.discover_files.return_value = files

    # --- Wire CodeAnalyzer mock ---
    analyzer_mock = MagicMock()
    analysis_result = MagicMock()
    analysis_result.chunks = []
    analysis_result.language = "python"
    analysis_result.path = "src/main.py"
    analysis_result.functions = main_ast.functions
    analysis_result.classes = main_ast.classes
    analysis_result.imports = main_ast.imports
    analysis_result.line_count = 200
    analyzer_mock.analyze_file.return_value = analysis_result

    # --- Wire HierarchicalExplorer mock ---
    explorer_mock = MagicMock()
    explorer_mock.explore.return_value = MagicMock(
        entries=[],
        total_files=6,
        total_dirs=2,
    )
    explorer_mock.format_result.return_value = "src/ (2 files)\ntests/ (3 files)"

    # --- Inject into server module ---
    srv._ast_service = svc_mock
    srv._context_mgr = ctx_mock
    srv._code_analyzer = analyzer_mock
    srv._explorer = explorer_mock

    return srv, ctx_mock, svc_mock, project_dir


def _init_git_repo(project_dir: str):
    """Initialize a minimal git repo with commits for history tools."""
    env = {**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "t@t.com",
           "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "t@t.com"}
    subprocess.run(["git", "init"], cwd=project_dir, capture_output=True, env=env)
    subprocess.run(["git", "add", "-A"], cwd=project_dir, capture_output=True, env=env)
    subprocess.run(["git", "commit", "-m", "Initial commit", "--allow-empty"],
                   cwd=project_dir, capture_output=True, env=env)
    # Second commit modifying a file
    (Path(project_dir) / "src" / "main.py").write_text(
        "import os\nfrom src.utils import helper\n\ndef main():\n    helper(42)\n    return 0\n"
    )
    subprocess.run(["git", "add", "-A"], cwd=project_dir, capture_output=True, env=env)
    subprocess.run(["git", "commit", "-m", "Update main"],
                   cwd=project_dir, capture_output=True, env=env)


# =========================================================================
# Category A: Pure logic tools (mock singletons only)
# =========================================================================


class TestAnalysisTools:
    """analysis_tools.py: 12 tools."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        self.srv, self.ctx, self.svc, self.project_dir = _build_audit_env(tmp_path, monkeypatch)
        yield
        self.srv._ast_service = None
        self.srv._context_mgr = None
        self.srv._code_analyzer = None
        self.srv._explorer = None

    def test_file_analysis(self):
        from attocode.code_intel.tools.analysis_tools import file_analysis
        result = file_analysis("src/main.py")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_impact_analysis(self):
        from attocode.code_intel.tools.analysis_tools import impact_analysis
        result = impact_analysis(["src/utils.py"])
        assert isinstance(result, str)

    def test_dependency_graph(self):
        from attocode.code_intel.tools.analysis_tools import dependency_graph
        result = dependency_graph("src/main.py", depth=2)
        assert isinstance(result, str)

    def test_hotspots(self):
        from attocode.code_intel.tools.analysis_tools import hotspots
        result = hotspots(top_n=5)
        assert isinstance(result, str)

    def test_cross_references(self):
        from attocode.code_intel.tools.analysis_tools import cross_references
        result = cross_references("helper")
        assert isinstance(result, str)

    def test_dependencies(self):
        from attocode.code_intel.tools.analysis_tools import dependencies
        result = dependencies("src/main.py")
        assert isinstance(result, str)

    def test_graph_query(self):
        from attocode.code_intel.tools.analysis_tools import graph_query
        result = graph_query(file="src/main.py", edge_type="IMPORTS", direction="outbound", depth=2)
        assert isinstance(result, str)

    def test_graph_dsl(self):
        from attocode.code_intel.tools.analysis_tools import graph_dsl
        result = graph_dsl("MATCH (a:src/main.py)-[IMPORTS]->(b) RETURN b")
        assert isinstance(result, str)

    def test_find_related(self):
        from attocode.code_intel.tools.analysis_tools import find_related
        result = find_related("src/main.py", top_k=5)
        assert isinstance(result, str)

    def test_community_detection(self):
        from attocode.code_intel.tools.analysis_tools import community_detection
        result = community_detection(min_community_size=2, max_communities=5)
        assert isinstance(result, str)

    def test_repo_map_ranked(self):
        from attocode.code_intel.tools.analysis_tools import repo_map_ranked
        result = repo_map_ranked(task_context="testing", token_budget=512)
        assert isinstance(result, str)

    def test_bug_scan(self, tmp_path):
        _init_git_repo(str(tmp_path))
        from attocode.code_intel.tools.analysis_tools import bug_scan
        result = bug_scan(base_branch="HEAD~1", min_confidence=0.3)
        assert isinstance(result, str)


class TestNavigationTools:
    """navigation_tools.py: 8 tools."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        self.srv, self.ctx, self.svc, self.project_dir = _build_audit_env(tmp_path, monkeypatch)
        yield
        self.srv._ast_service = None
        self.srv._context_mgr = None
        self.srv._code_analyzer = None
        self.srv._explorer = None

    def test_repo_map(self):
        from attocode.code_intel.tools.navigation_tools import repo_map
        result = repo_map(include_symbols=True, max_tokens=2000)
        assert isinstance(result, str)

    def test_symbols(self):
        from attocode.code_intel.tools.navigation_tools import symbols
        result = symbols("src/main.py")
        assert isinstance(result, str)

    def test_search_symbols(self):
        from attocode.code_intel.tools.navigation_tools import search_symbols
        result = search_symbols("helper", limit=10)
        assert isinstance(result, str)

    def test_explore_codebase(self):
        from attocode.code_intel.tools.navigation_tools import explore_codebase
        result = explore_codebase(path="", max_items=10)
        assert isinstance(result, str)

    def test_project_summary(self):
        from attocode.code_intel.tools.navigation_tools import project_summary
        result = project_summary(max_tokens=2000)
        assert isinstance(result, str)

    def test_bootstrap(self):
        from attocode.code_intel.tools.navigation_tools import bootstrap
        result = bootstrap(task_hint="testing", max_tokens=4000)
        assert isinstance(result, str)

    def test_conventions(self):
        from attocode.code_intel.tools.navigation_tools import conventions
        result = conventions(sample_size=10)
        assert isinstance(result, str)

    def test_relevant_context(self):
        from attocode.code_intel.tools.navigation_tools import relevant_context
        result = relevant_context(files=["src/main.py"], depth=1, max_tokens=2000)
        assert isinstance(result, str)

    def test_reindex(self):
        from attocode.code_intel.tools.navigation_tools import reindex
        result = reindex(force=False)
        assert isinstance(result, str)


class TestDeadCodeTool:
    """dead_code_tools.py: 1 tool, 3 levels."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        self.srv, self.ctx, self.svc, self.project_dir = _build_audit_env(tmp_path, monkeypatch)
        yield
        self.srv._ast_service = None
        self.srv._context_mgr = None

    def test_dead_code_symbol(self):
        from attocode.code_intel.tools.dead_code_tools import dead_code
        result = dead_code(level="symbol", top_n=10)
        assert isinstance(result, str)

    def test_dead_code_file(self):
        from attocode.code_intel.tools.dead_code_tools import dead_code
        result = dead_code(level="file", top_n=10)
        assert isinstance(result, str)

    def test_dead_code_module(self):
        from attocode.code_intel.tools.dead_code_tools import dead_code
        result = dead_code(level="module", top_n=10)
        assert isinstance(result, str)


class TestDistillTool:
    """distill_tools.py: 1 tool, 3 levels."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        self.srv, self.ctx, self.svc, self.project_dir = _build_audit_env(tmp_path, monkeypatch)
        yield
        self.srv._ast_service = None
        self.srv._context_mgr = None

    def test_distill_signatures(self):
        from attocode.code_intel.tools.distill_tools import distill
        result = distill(level="signatures", max_tokens=2000)
        assert isinstance(result, str)

    def test_distill_structure(self):
        from attocode.code_intel.tools.distill_tools import distill
        result = distill(level="structure", max_tokens=2000)
        assert isinstance(result, str)

    def test_distill_full(self):
        from attocode.code_intel.tools.distill_tools import distill
        result = distill(level="full", max_tokens=2000)
        assert isinstance(result, str)


# =========================================================================
# Category B: Git-dependent tools
# =========================================================================


class TestHistoryTools:
    """history_tools.py: 5 tools + bug_scan from analysis_tools."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        self.srv, self.ctx, self.svc, self.project_dir = _build_audit_env(tmp_path, monkeypatch)
        _init_git_repo(self.project_dir)
        # Reset temporal analyzer singleton so it picks up the test repo
        import attocode.code_intel.tools.history_tools as ht
        ht._temporal_analyzer = None
        yield
        self.srv._ast_service = None
        self.srv._context_mgr = None
        ht._temporal_analyzer = None

    def test_code_evolution(self):
        from attocode.code_intel.tools.history_tools import code_evolution
        result = code_evolution(path="src/main.py")
        assert isinstance(result, str)

    def test_recent_changes(self):
        from attocode.code_intel.tools.history_tools import recent_changes
        result = recent_changes(days=30, top_n=5)
        assert isinstance(result, str)

    def test_change_coupling(self):
        from attocode.code_intel.tools.history_tools import change_coupling
        result = change_coupling(file="src/main.py", days=90)
        assert isinstance(result, str)

    def test_churn_hotspots(self):
        from attocode.code_intel.tools.history_tools import churn_hotspots
        result = churn_hotspots(days=90, top_n=5)
        assert isinstance(result, str)

    def test_merge_risk(self):
        from attocode.code_intel.tools.history_tools import merge_risk
        result = merge_risk(files=["src/main.py"], days=90)
        assert isinstance(result, str)


# =========================================================================
# Category C: SQLite-dependent tools (ADR + Learning)
# =========================================================================


class TestADRTools:
    """adr_tools.py: 4 tools."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        self.srv, self.ctx, self.svc, self.project_dir = _build_audit_env(tmp_path, monkeypatch)
        # Ensure .attocode dir exists for SQLite stores
        (tmp_path / ".attocode").mkdir(exist_ok=True)
        # Reset ADR store singleton
        import attocode.code_intel.tools.adr_tools as at
        at._adr_store = None
        yield
        at._adr_store = None
        self.srv._ast_service = None
        self.srv._context_mgr = None

    def test_record_adr(self):
        from attocode.code_intel.tools.adr_tools import record_adr
        result = record_adr(
            title="Use PostgreSQL",
            context="Need a relational database",
            decision="Use PostgreSQL for all storage",
            consequences="Must maintain migrations",
        )
        assert isinstance(result, str)
        assert "ADR" in result or "adr" in result.lower() or "#" in result

    def test_list_adrs(self):
        from attocode.code_intel.tools.adr_tools import record_adr, list_adrs
        record_adr(title="Test ADR", context="ctx", decision="dec")
        result = list_adrs()
        assert isinstance(result, str)

    def test_get_adr(self):
        from attocode.code_intel.tools.adr_tools import record_adr, get_adr
        record_adr(title="Test ADR", context="ctx", decision="dec")
        result = get_adr(number=1)
        assert isinstance(result, str)

    def test_update_adr_status(self):
        from attocode.code_intel.tools.adr_tools import record_adr, update_adr_status
        record_adr(title="Test ADR", context="ctx", decision="dec")
        result = update_adr_status(number=1, status="accepted")
        assert isinstance(result, str)


class TestLearningTools:
    """learning_tools.py: 4 tools."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        self.srv, self.ctx, self.svc, self.project_dir = _build_audit_env(tmp_path, monkeypatch)
        (tmp_path / ".attocode").mkdir(exist_ok=True)
        # Reset memory store
        self.srv._memory_store = None
        yield
        self.srv._memory_store = None
        self.srv._ast_service = None
        self.srv._context_mgr = None

    def test_record_learning(self):
        from attocode.code_intel.tools.learning_tools import record_learning
        result = record_learning(
            type="pattern",
            description="Use dataclasses for DTOs",
            details="Prefer dataclasses over dicts for type safety",
        )
        assert isinstance(result, str)

    def test_recall(self):
        from attocode.code_intel.tools.learning_tools import record_learning, recall
        record_learning(type="pattern", description="Use dataclasses")
        result = recall(query="dataclasses")
        assert isinstance(result, str)

    def test_learning_feedback(self):
        from attocode.code_intel.tools.learning_tools import record_learning, learning_feedback
        record_learning(type="pattern", description="Use dataclasses")
        result = learning_feedback(learning_id=1, helpful=True)
        assert isinstance(result, str)

    def test_list_learnings(self):
        from attocode.code_intel.tools.learning_tools import record_learning, list_learnings
        record_learning(type="pattern", description="Use dataclasses")
        result = list_learnings()
        assert isinstance(result, str)


# =========================================================================
# Category D: LSP tools (async, mocked LSP manager)
# =========================================================================


class TestLSPTools:
    """lsp_tools.py: 5 tools (3 async, 1 sync, 1 async)."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        self.srv, self.ctx, self.svc, self.project_dir = _build_audit_env(tmp_path, monkeypatch)

        import attocode.code_intel.tools.lsp_tools as lt

        # Build LSP mock
        lsp_mock = MagicMock()

        # Mock Location-like object
        mock_location = MagicMock()
        mock_location.uri = f"file://{tmp_path}/src/utils.py"
        mock_range = MagicMock()
        mock_range.start.line = 3
        mock_range.start.character = 4
        mock_range.end.line = 3
        mock_range.end.character = 10
        mock_location.range = mock_range

        lsp_mock.get_definition.return_value = mock_location
        lsp_mock.get_references.return_value = [mock_location]
        lsp_mock.get_hover.return_value = "def helper(value: int) -> str"
        lsp_mock.get_diagnostics.return_value = []
        lsp_mock.on_result_callback = None

        lt._lsp_manager = lsp_mock
        yield
        lt._lsp_manager = None
        self.srv._ast_service = None
        self.srv._context_mgr = None

    @pytest.mark.asyncio
    async def test_lsp_definition(self):
        from attocode.code_intel.tools.lsp_tools import lsp_definition
        result = await lsp_definition(file="src/main.py", line=5, col=4)
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_lsp_references(self):
        from attocode.code_intel.tools.lsp_tools import lsp_references
        result = await lsp_references(file="src/utils.py", line=3, col=4)
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_lsp_hover(self):
        from attocode.code_intel.tools.lsp_tools import lsp_hover
        result = await lsp_hover(file="src/utils.py", line=3, col=4)
        assert isinstance(result, str)

    def test_lsp_diagnostics(self):
        from attocode.code_intel.tools.lsp_tools import lsp_diagnostics
        result = lsp_diagnostics(file="src/main.py")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_lsp_enrich(self):
        from attocode.code_intel.tools.lsp_tools import lsp_enrich
        result = await lsp_enrich(files=["src/main.py"])
        assert isinstance(result, str)


# =========================================================================
# Category E: External service tools (semantic search, security, trigram)
# =========================================================================


class TestSearchTools:
    """search_tools.py: 4 tools."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        self.srv, self.ctx, self.svc, self.project_dir = _build_audit_env(tmp_path, monkeypatch)

        import attocode.code_intel.tools.search_tools as st

        # Mock semantic search manager
        sem_mock = MagicMock()
        sem_mock.search.return_value = []
        sem_mock.format_results.return_value = "No results found."
        progress_mock = MagicMock()
        progress_mock.total_files = 6
        progress_mock.indexed_files = 6
        progress_mock.failed_files = 0
        progress_mock.status = "complete"
        progress_mock.provider_name = "bm25"
        progress_mock.coverage = 1.0
        progress_mock.elapsed_seconds = 0.5
        sem_mock.get_index_progress.return_value = progress_mock
        sem_mock.provider_name = "bm25"
        sem_mock.is_available = True
        sem_mock.is_index_ready.return_value = True
        st._semantic_search = sem_mock

        # Mock security scanner
        sec_mock = MagicMock()
        sec_mock.scan.return_value = MagicMock(
            findings=[], score=100,
            summary="No security issues found.",
        )
        sec_mock.format_report.return_value = "Security score: 100/100\nNo issues found."
        st._security_scanner = sec_mock

        # Mock trigram index
        tri_mock = MagicMock()
        tri_mock.query.return_value = [
            MagicMock(path="src/main.py", line=5, text="    helper(42)", score=1.0),
        ]
        tri_mock.built = True
        st._trigram_index = tri_mock

        yield
        st._semantic_search = None
        st._security_scanner = None
        st._trigram_index = None
        self.srv._ast_service = None
        self.srv._context_mgr = None

    def test_semantic_search(self):
        from attocode.code_intel.tools.search_tools import semantic_search
        result = semantic_search(query="helper function", top_k=5)
        assert isinstance(result, str)

    def test_semantic_search_status(self):
        from attocode.code_intel.tools.search_tools import semantic_search_status
        result = semantic_search_status()
        assert isinstance(result, str)

    def test_security_scan(self):
        from attocode.code_intel.tools.search_tools import security_scan
        result = security_scan(mode="full")
        assert isinstance(result, str)

    def test_fast_search(self):
        from attocode.code_intel.tools.search_tools import fast_search
        result = fast_search(pattern="helper", max_results=10)
        assert isinstance(result, str)


class TestReadinessTool:
    """readiness_tools.py: 1 tool (orchestrates other tools internally)."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        self.srv, self.ctx, self.svc, self.project_dir = _build_audit_env(tmp_path, monkeypatch)
        _init_git_repo(self.project_dir)
        yield
        self.srv._ast_service = None
        self.srv._context_mgr = None

    def test_readiness_report(self):
        from attocode.code_intel.tools.readiness_tools import readiness_report
        result = readiness_report(phases=[1], min_severity="warning")
        assert isinstance(result, str)


# =========================================================================
# Category F: Server-level tool
# =========================================================================


class TestServerTools:
    """server.py: notify_file_changed."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        self.srv, self.ctx, self.svc, self.project_dir = _build_audit_env(tmp_path, monkeypatch)
        yield
        self.srv._ast_service = None
        self.srv._context_mgr = None

    def test_notify_file_changed(self):
        from attocode.code_intel.server import notify_file_changed
        result = notify_file_changed(files=["src/main.py"])
        assert isinstance(result, str)
