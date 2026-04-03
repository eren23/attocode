"""Unit tests for learning_tools MCP tools.

Tests the following tools:
- record_learning
- recall
- learning_feedback
- list_learnings

Run:
    pytest tests/unit/code_intel/tools/test_learning_tools.py -v
"""

from __future__ import annotations

import pytest


class TestLearningTools:
    """Tests for learning_tools.py functions."""

    @pytest.fixture(autouse=True)
    def _setup(self, tool_test_project, mock_ast_service,
               mock_code_intel_service, mock_context_manager):
        """Setup mocks for learning tool tests."""
        import attocode.code_intel._shared as ci_shared
        import attocode.code_intel.server as srv

        # Reset singletons
        ci_shared._ast_service = None
        ci_shared._context_mgr = None
        ci_shared._service = None

        srv._ast_service = mock_ast_service
        srv._context_mgr = mock_context_manager

        # Ensure .attocode dir exists
        (tool_test_project / ".attocode").mkdir(exist_ok=True)

        self._srv = srv

        yield

        # Cleanup
        srv._ast_service = None
        srv._context_mgr = None
        srv._memory_store = None

    def test_record_learning(self):
        """Test record_learning returns a string."""
        from attocode.code_intel.tools.learning_tools import record_learning

        result = record_learning(
            type="pattern",
            description="Use dataclasses for DTOs",
            details="Prefer dataclasses over dicts for type safety",
        )
        assert isinstance(result, str)

    def test_recall(self):
        """Test recall returns a string."""
        from attocode.code_intel.tools.learning_tools import record_learning, recall

        record_learning(type="pattern", description="Use dataclasses")
        result = recall(query="dataclasses")
        assert isinstance(result, str)

    def test_learning_feedback(self):
        """Test learning_feedback returns a string."""
        from attocode.code_intel.tools.learning_tools import record_learning, learning_feedback

        record_learning(type="pattern", description="Use dataclasses")
        result = learning_feedback(learning_id=1, helpful=True)
        assert isinstance(result, str)

    def test_list_learnings(self):
        """Test list_learnings returns a string."""
        from attocode.code_intel.tools.learning_tools import record_learning, list_learnings

        record_learning(type="pattern", description="Use dataclasses")
        result = list_learnings()
        assert isinstance(result, str)
