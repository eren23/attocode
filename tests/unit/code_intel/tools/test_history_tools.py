"""Unit tests for history_tools MCP tools.

Tests the following tools:
- code_evolution
- recent_changes
- change_coupling
- churn_hotspots
- merge_risk

Run:
    pytest tests/unit/code_intel/tools/test_history_tools.py -v
"""

from __future__ import annotations

import subprocess

import pytest


class TestHistoryTools:
    """Tests for history_tools.py functions."""

    @pytest.fixture(autouse=True)
    def _setup(self, tool_test_project, mock_ast_service,
               mock_code_intel_service, mock_context_manager):
        """Setup mocks for history tool tests."""
        import attocode.code_intel._shared as ci_shared
        import attocode.code_intel.server as srv
        import attocode.code_intel.tools.history_tools as ht

        # Reset singletons
        ci_shared._ast_service = None
        ci_shared._context_mgr = None
        ci_shared._service = None

        srv._ast_service = mock_ast_service
        srv._context_mgr = mock_context_manager

        # Initialize git repo for history tools
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
        subprocess.run(["git", "commit", "-m", "Initial commit"],
                       cwd=str(tool_test_project), capture_output=True, env=env)

        # Reset temporal analyzer singleton
        ht._temporal_analyzer = None

        self._srv = srv
        self._project_dir = str(tool_test_project)

        yield

        # Cleanup
        srv._ast_service = None
        srv._context_mgr = None
        ht._temporal_analyzer = None

    def test_code_evolution(self):
        """Test code_evolution returns a string."""
        from attocode.code_intel.tools.history_tools import code_evolution

        result = code_evolution(path="src/main.py")
        assert isinstance(result, str)

    def test_recent_changes(self):
        """Test recent_changes returns a string."""
        from attocode.code_intel.tools.history_tools import recent_changes

        result = recent_changes(days=30, top_n=5)
        assert isinstance(result, str)

    def test_change_coupling(self):
        """Test change_coupling returns a string."""
        from attocode.code_intel.tools.history_tools import change_coupling

        result = change_coupling(file="src/main.py", days=90)
        assert isinstance(result, str)

    def test_churn_hotspots(self):
        """Test churn_hotspots returns a string."""
        from attocode.code_intel.tools.history_tools import churn_hotspots

        result = churn_hotspots(days=90, top_n=5)
        assert isinstance(result, str)

    def test_merge_risk(self):
        """Test merge_risk returns a string."""
        from attocode.code_intel.tools.history_tools import merge_risk

        result = merge_risk(files=["src/main.py"], days=90)
        assert isinstance(result, str)
