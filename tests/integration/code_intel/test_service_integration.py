"""Integration tests: real CodeIntelService on a sample project.

These tests verify the service actually works end-to-end — no mocks.
"""

from __future__ import annotations

import pytest

from attocode.code_intel.service import CodeIntelService

pytestmark = pytest.mark.integration


def test_service_initializes(service: CodeIntelService, sample_project_dir: str):
    """CodeIntelService can be constructed on a real directory."""
    assert service.project_dir == sample_project_dir


def test_repo_map_returns_tree(service: CodeIntelService):
    """repo_map() returns a non-empty string containing file paths."""
    result = service.repo_map(include_symbols=True, max_tokens=6000)
    assert isinstance(result, str)
    assert len(result) > 0
    # Should contain at least one of our fixture files
    assert "main.py" in result or "utils.py" in result or "models.py" in result


def test_symbols_finds_known_class(service: CodeIntelService):
    """symbols() finds the App class from main.py."""
    result = service.symbols("main.py")
    assert isinstance(result, str)
    assert "App" in result


def test_search_symbols_finds_by_name(service: CodeIntelService):
    """search_symbols() can find a symbol by name."""
    result = service.search_symbols("App")
    assert isinstance(result, str)
    assert len(result) > 0
    # Should mention the App class or main.py
    assert "App" in result


def test_dependencies_reports_imports(service: CodeIntelService):
    """dependencies() lists known imports from main.py."""
    result = service.dependencies("main.py")
    assert isinstance(result, str)
    # main.py imports from utils and models
    assert "utils" in result.lower() or "models" in result.lower() or "import" in result.lower()


def test_file_analysis_returns_structure(service: CodeIntelService):
    """file_analysis() returns structured output for a file."""
    result = service.file_analysis("main.py")
    assert isinstance(result, str)
    assert len(result) > 0
    # Should contain some structural info
    lower = result.lower()
    assert "main.py" in lower or "class" in lower or "line" in lower or "python" in lower


def test_learning_roundtrip(service: CodeIntelService):
    """record_learning() + recall() round-trips correctly."""
    record_result = service.record_learning(
        type="convention",
        description="Always use snake_case for function names",
        details="This is a test learning for integration tests",
        scope="sample_project",
        confidence=0.9,
    )
    assert isinstance(record_result, str)

    recall_result = service.recall(query="snake_case function names", scope="sample_project")
    assert isinstance(recall_result, str)
    assert "snake_case" in recall_result or "convention" in recall_result.lower()


def test_explore_codebase_lists_files(service: CodeIntelService):
    """explore_codebase() returns a non-empty listing."""
    result = service.explore_codebase()
    assert isinstance(result, str)
    assert len(result) > 0
    # Should list at least one of our fixture files
    assert "main.py" in result or "utils.py" in result or "models.py" in result
