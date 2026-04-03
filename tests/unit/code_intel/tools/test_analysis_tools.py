"""Unit tests for analysis_tools MCP tools.

Tests the following tools:
- file_analysis
- impact_analysis
- dependency_graph
- hotspots
- cross_references
- dependencies
- graph_query
- graph_dsl
- find_related
- community_detection
- repo_map_ranked
- bug_scan

Run:
    pytest tests/unit/code_intel/tools/test_analysis_tools.py -v
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import pytest


class TestAnalysisTools:
    """Tests for analysis_tools.py functions."""

    @pytest.fixture(autouse=True)
    def _setup(self, tool_test_project, mock_ast_service,
               mock_code_intel_service, mock_context_manager):
        """Setup mocks for all analysis tool tests."""
        import attocode.code_intel._shared as ci_shared
        import attocode.code_intel.server as srv

        # Reset singletons
        ci_shared._ast_service = None
        ci_shared._context_mgr = None
        ci_shared._service = None

        # Setup mock analyzer
        analysis_result = MagicMock()
        analysis_result.chunks = []
        analysis_result.language = "python"
        analysis_result.path = "src/main.py"
        analysis_result.functions = []
        analysis_result.classes = []
        analysis_result.imports = []
        analysis_result.line_count = 50

        srv._ast_service = mock_ast_service
        srv._context_mgr = mock_context_manager
        srv._code_analyzer = MagicMock()
        srv._code_analyzer.analyze_file.return_value = analysis_result

        self._srv = srv
        self._project_dir = str(tool_test_project)

        yield

        # Cleanup
        srv._ast_service = None
        srv._context_mgr = None
        srv._code_analyzer = None
        srv._explorer = None

    def test_file_analysis(self):
        """Test file_analysis returns a string."""
        from attocode.code_intel.tools.analysis_tools import file_analysis

        result = file_analysis("src/main.py")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_impact_analysis(self):
        """Test impact_analysis returns a string."""
        from attocode.code_intel.tools.analysis_tools import impact_analysis

        result = impact_analysis(["src/utils.py"])
        assert isinstance(result, str)

    def test_dependency_graph(self):
        """Test dependency_graph returns a string."""
        from attocode.code_intel.tools.analysis_tools import dependency_graph

        result = dependency_graph("src/main.py", depth=2)
        assert isinstance(result, str)

    def test_hotspots(self):
        """Test hotspots returns a string."""
        from attocode.code_intel.tools.analysis_tools import hotspots

        result = hotspots(top_n=5)
        assert isinstance(result, str)

    def test_cross_references(self):
        """Test cross_references returns a string."""
        from attocode.code_intel.tools.analysis_tools import cross_references

        result = cross_references("helper")
        assert isinstance(result, str)

    def test_dependencies(self):
        """Test dependencies returns a string."""
        from attocode.code_intel.tools.analysis_tools import dependencies

        result = dependencies("src/main.py")
        assert isinstance(result, str)

    def test_graph_query(self):
        """Test graph_query returns a string."""
        from attocode.code_intel.tools.analysis_tools import graph_query

        result = graph_query(
            file="src/main.py",
            edge_type="IMPORTS",
            direction="outbound",
            depth=2
        )
        assert isinstance(result, str)

    def test_graph_dsl(self):
        """Test graph_dsl returns a string."""
        from attocode.code_intel.tools.analysis_tools import graph_dsl

        result = graph_dsl("MATCH (a:src/main.py)-[IMPORTS]->(b) RETURN b")
        assert isinstance(result, str)

    def test_find_related(self):
        """Test find_related returns a string."""
        from attocode.code_intel.tools.analysis_tools import find_related

        result = find_related("src/main.py", top_k=5)
        assert isinstance(result, str)

    def test_community_detection(self):
        """Test community_detection returns a string."""
        from attocode.code_intel.tools.analysis_tools import community_detection

        result = community_detection(min_community_size=2, max_communities=5)
        assert isinstance(result, str)

    def test_repo_map_ranked(self):
        """Test repo_map_ranked returns a string."""
        from attocode.code_intel.tools.analysis_tools import repo_map_ranked

        result = repo_map_ranked(task_context="testing", token_budget=512)
        assert isinstance(result, str)

    def test_bug_scan(self, tool_test_project):
        """Test bug_scan returns a string (requires git repo)."""
        # Initialize a git repo for bug_scan
        env = {
            **subprocess.os.environ,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "t@t.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "t@t.com",
        }
        subprocess.run(["git", "init"], cwd=str(tool_test_project),
                       capture_output=True, env=env)
        subprocess.run(["git", "add", "-A"], cwd=str(tool_test_project),
                       capture_output=True, env=env)
        subprocess.run(["git", "commit", "-m", "Initial"],
                       cwd=str(tool_test_project), capture_output=True, env=env)

        from attocode.code_intel.tools.analysis_tools import bug_scan

        result = bug_scan(base_branch="HEAD~1", min_confidence=0.3)
        assert isinstance(result, str)
