"""Tests for enrich_task_context_async() in task_dispatcher.py.

Verifies the side-query pattern for code-intel enrichment.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from attoswarm.coordinator.task_dispatcher import enrich_task_context_async
from attoswarm.protocol.models import TaskSpec


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_task(
    task_id: str = "t1",
    target_files: list[str] | None = None,
) -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        title="Test task",
        description="A test task",
        target_files=target_files or [],
    )


def _make_code_intel(
    *,
    impact: dict | None = None,
    symbols: list | None = None,
    deps: dict | None = None,
) -> MagicMock:
    """Build a mock code-intel service with sync methods."""
    ci = MagicMock()

    if impact is not None:
        ci.impact_analysis_data = MagicMock(return_value=impact)
    else:
        # Remove the attribute so hasattr returns False
        del ci.impact_analysis_data

    if symbols is not None:
        ci.symbols_data = MagicMock(return_value=symbols)
    else:
        del ci.symbols_data

    if deps is not None:
        ci.dependencies_data = MagicMock(return_value=deps)
    else:
        del ci.dependencies_data

    return ci


# ---------------------------------------------------------------------------
# Test 6a: No target_files -> empty result
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enrich_returns_empty_on_no_target_files():
    """Task with no target_files should short-circuit to {}."""
    task = _make_task(target_files=[])
    ci = _make_code_intel(
        impact={"impacted_files": ["x.py"], "total_impacted": 1},
    )
    result = await enrich_task_context_async(task, ci)
    assert result == {}


# ---------------------------------------------------------------------------
# Test 6b: None code_intel -> empty result
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enrich_returns_empty_on_no_code_intel():
    """None code_intel should short-circuit to {}."""
    task = _make_task(target_files=["main.py"])
    result = await enrich_task_context_async(task, None)
    assert result == {}


# ---------------------------------------------------------------------------
# Test 6c: Slow code_intel -> graceful timeout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enrich_handles_timeout_gracefully():
    """Slow code_intel should return partial or {} without raising."""
    ci = MagicMock()

    def _slow_impact(files):
        import time
        time.sleep(5)  # Will exceed the timeout
        return {"impacted_files": ["a.py"]}

    ci.impact_analysis_data = _slow_impact
    # Remove other attributes
    del ci.symbols_data
    del ci.dependencies_data

    task = _make_task(target_files=["main.py"])

    # Very short timeout to trigger TimeoutError
    result = await enrich_task_context_async(task, ci, timeout=0.05)

    # Should return {} or partial -- never raise
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Test 6d: Parallel results collected correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enrich_collects_parallel_results():
    """Mock code_intel with impact/symbols/deps should produce all keys."""
    ci = _make_code_intel(
        impact={
            "impacted_files": [{"file": "a.py"}, {"file": "b.py"}],
            "total_impacted": 2,
        },
        symbols=[{"name": "MyClass", "kind": "class"}],
        deps={"imports": ["os", "sys"], "imported_by": ["main.py"]},
    )

    task = _make_task(target_files=["src/lib.py"])

    result = await enrich_task_context_async(task, ci, timeout=5.0)

    # impact should be present
    assert "impact" in result
    assert "a.py" in result["impact"]

    # symbols should be present
    assert "symbols" in result
    assert "MyClass" in result["symbols"]

    # dependencies should be present
    assert "dependencies" in result
    assert "os" in result["dependencies"] or "sys" in result["dependencies"]
