"""Shared fixtures for code-intel MCP tool unit tests.

Provides standardized fixtures for testing individual MCP tools.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, PropertyMock

import pytest

if TYPE_CHECKING:
    from attocode.code_intel.service import CodeIntelService
    from attocode.integrations.context.ast_service import ASTService


# ---------------------------------------------------------------------------
# Test project creation
# ---------------------------------------------------------------------------


@pytest.fixture
def tool_test_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a minimal project for tool testing.

    Sets up:
        - src/main.py (with main, cli, helper functions and BaseProcessor class)
        - src/utils.py (with helper, _internal_helper and DataProcessor class)
        - tests/test_main.py
        - tests/test_utils.py
        - pyproject.toml
    """
    project_dir = str(tmp_path)
    monkeypatch.setenv("ATTOCODE_PROJECT_DIR", project_dir)

    src = tmp_path / "src"
    tests = tmp_path / "tests"

    src.mkdir(parents=True, exist_ok=True)
    tests.mkdir(parents=True, exist_ok=True)

    (src / "__init__.py").write_text("")
    (src / "main.py").write_text(
        "import os\nfrom src.utils import helper\n\ndef main():\n    helper(42)\n\ndef cli(args):\n    return 0\n"
    )
    (src / "utils.py").write_text(
        "def helper(value):\n    return str(value)\n\ndef _internal_helper(x):\n    return x * 2\n\nclass BaseProcessor:\n    def process(self): pass\n\nclass DataProcessor(BaseProcessor):\n    def __init__(self, name):\n        self.name = name\n    def process(self):\n        return f\"Processed: {self.name}\"\n"
    )
    (tests / "__init__.py").write_text("")
    (tests / "test_main.py").write_text(
        "import pytest\ndef test_basic(): pass\ndef test_advanced(): pass\n"
    )
    (tests / "test_utils.py").write_text(
        "import pytest\ndef test_helper(): pass\n"
    )
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test"\nversion = "0.1.0"\n'
    )

    yield tmp_path

    monkeypatch.delenv("ATTOCODE_PROJECT_DIR", raising=False)


@pytest.fixture
def mock_ast_service(tool_test_project: Path):
    """Provide a mock ASTService for tool tests."""
    from attocode.integrations.context.cross_references import SymbolLocation

    mock = MagicMock()
    mock.initialized = True
    mock._to_rel = lambda path: os.path.relpath(path, str(tool_test_project))

    mock.get_file_symbols.return_value = [
        SymbolLocation(name="main", qualified_name="main", kind="function",
                       file_path="src/main.py", start_line=3, end_line=4),
        SymbolLocation(name="helper", qualified_name="helper", kind="function",
                       file_path="src/utils.py", start_line=1, end_line=2),
    ]
    mock.find_symbol.return_value = [
        SymbolLocation(name="helper", qualified_name="helper", kind="function",
                       file_path="src/utils.py", start_line=1, end_line=2),
    ]
    mock.search_symbol.return_value = [
        (SymbolLocation(name="helper", qualified_name="helper", kind="function",
                        file_path="src/utils.py", start_line=1, end_line=2), 0.95),
    ]
    mock.get_callers.return_value = []
    mock.get_dependencies.return_value = []
    mock.get_dependents.return_value = []
    mock.get_impact.return_value = set()

    return mock


@pytest.fixture
def mock_code_intel_service(tool_test_project: Path, mock_ast_service):
    """Provide a mock CodeIntelService for tool tests."""
    mock = MagicMock()
    mock.project_dir = str(tool_test_project)
    mock.search_symbols.return_value = ""
    mock.get_repo_map.return_value = {}
    mock.get_dependencies.return_value = {}

    return mock


@pytest.fixture
def mock_context_manager(tool_test_project: Path):
    """Provide a mock CodebaseContextManager for tool tests."""
    from attocode.integrations.context.codebase_context import FileInfo, RepoMap, DependencyGraph

    files = [
        FileInfo(path=str(tool_test_project / "src/main.py"),
                 relative_path="src/main.py", size=500, language="python",
                 importance=0.9, line_count=50),
        FileInfo(path=str(tool_test_project / "src/utils.py"),
                 relative_path="src/utils.py", size=500, language="python",
                 importance=0.7, line_count=50),
    ]

    repo_map = RepoMap(
        tree="src/\n  main.py\n  utils.py",
        files=files, total_files=2, total_lines=100,
        languages={"python": 2},
    )

    dep_graph = DependencyGraph()

    mock = MagicMock()
    mock._files = files
    mock.root_dir = str(tool_test_project)
    mock._dep_graph = dep_graph
    type(mock).dependency_graph = PropertyMock(return_value=dep_graph)
    mock.get_repo_map.return_value = repo_map

    return mock
