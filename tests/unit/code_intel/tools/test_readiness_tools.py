"""Unit tests for readiness_tools MCP tool.

Tests the readiness_report tool.

Run:
    pytest tests/unit/code_intel/tools/test_readiness_tools.py -v
"""

from __future__ import annotations

import subprocess

import pytest


class TestReadinessTools:
    """Tests for readiness_tools.py functions."""

    @pytest.fixture(autouse=True)
    def _setup(self, tool_test_project, mock_ast_service,
               mock_code_intel_service, mock_context_manager):
        """Setup mocks for readiness tool tests."""
        import attocode.code_intel._shared as ci_shared
        import attocode.code_intel.server as srv

        # Reset singletons
        ci_shared._ast_service = None
        ci_shared._context_mgr = None
        ci_shared._service = None

        srv._ast_service = mock_ast_service
        srv._context_mgr = mock_context_manager

        # Initialize git repo for readiness report
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

        self._srv = srv

        yield

        # Cleanup
        srv._ast_service = None
        srv._context_mgr = None

    def test_readiness_report(self):
        """Test readiness_report returns a string."""
        from attocode.code_intel.tools.readiness_tools import readiness_report

        result = readiness_report(phases=[1], min_severity="warning")
        assert isinstance(result, str)
