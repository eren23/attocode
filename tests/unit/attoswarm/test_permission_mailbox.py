"""Tests for _evaluate_permission() and auto-approve/deny tool sets.

Exercises the permission mailbox logic from HybridCoordinator without
instantiating the full coordinator -- we create a minimal mock and call
the method directly.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from attoswarm.protocol.models import PermissionRequest, PermissionResponse, RoleSpec


# ---------------------------------------------------------------------------
# Import the constants and method from the loop module.
# We import them at module level so they are available as references.
# ---------------------------------------------------------------------------

from attoswarm.coordinator.loop import (
    _AUTO_APPROVE_TOOLS,
    _AUTO_DENY_TOOLS,
    HybridCoordinator,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(
    tool_name: str,
    agent_id: str = "agent-1",
    task_id: str = "t1",
) -> PermissionRequest:
    return PermissionRequest(
        request_id="req-001",
        agent_id=agent_id,
        task_id=task_id,
        tool_name=tool_name,
        tool_args_summary="{}",
        danger_level="low",
    )


def _make_coordinator_stub(
    role_by_agent: dict[str, RoleSpec] | None = None,
) -> MagicMock:
    """Build a minimal mock that has enough attributes for _evaluate_permission."""
    stub = MagicMock(spec=HybridCoordinator)
    stub.role_by_agent = role_by_agent or {}
    # Bind the real _evaluate_permission method to the stub
    stub._evaluate_permission = HybridCoordinator._evaluate_permission.__get__(stub)
    return stub


# ---------------------------------------------------------------------------
# Test 8a: auto-approve read tools
# ---------------------------------------------------------------------------


def test_auto_approve_read_tools():
    """Read-only tools like 'grep' should be auto-approved."""
    coordinator = _make_coordinator_stub()
    req = _make_request(tool_name="grep")
    resp = coordinator._evaluate_permission(req)

    assert isinstance(resp, PermissionResponse)
    assert resp.decision == "approved"
    assert "read-only" in resp.reason


def test_auto_approve_all_safe_tools():
    """All tools in _AUTO_APPROVE_TOOLS should be approved."""
    coordinator = _make_coordinator_stub()
    for tool in _AUTO_APPROVE_TOOLS:
        req = _make_request(tool_name=tool)
        resp = coordinator._evaluate_permission(req)
        assert resp.decision == "approved", f"{tool} should be auto-approved"


# ---------------------------------------------------------------------------
# Test 8b: auto-deny dangerous tools
# ---------------------------------------------------------------------------


def test_auto_deny_dangerous_tools():
    """Dangerous tools like 'delete_file' should be auto-denied."""
    coordinator = _make_coordinator_stub()
    req = _make_request(tool_name="delete_file")
    resp = coordinator._evaluate_permission(req)

    assert isinstance(resp, PermissionResponse)
    assert resp.decision == "rejected"
    assert "not permitted" in resp.reason


def test_auto_deny_all_dangerous_tools():
    """All tools in _AUTO_DENY_TOOLS should be rejected."""
    coordinator = _make_coordinator_stub()
    for tool in _AUTO_DENY_TOOLS:
        req = _make_request(tool_name=tool)
        resp = coordinator._evaluate_permission(req)
        assert resp.decision == "rejected", f"{tool} should be auto-denied"


# ---------------------------------------------------------------------------
# Test 8c: write_access role -> approved
# ---------------------------------------------------------------------------


def test_write_access_role_approved():
    """An agent whose role has write_access=True should be approved for write tools."""
    role = RoleSpec(
        role_id="worker",
        role_type="worker",
        backend="claude",
        model="opus",
        write_access=True,
    )
    coordinator = _make_coordinator_stub(role_by_agent={"agent-1": role})
    req = _make_request(tool_name="write_file", agent_id="agent-1")
    resp = coordinator._evaluate_permission(req)

    assert resp.decision == "approved"
    assert "write access" in resp.reason


# ---------------------------------------------------------------------------
# Test 8d: no write_access -> rejected
# ---------------------------------------------------------------------------


def test_no_write_access_rejected():
    """An agent without write_access should be rejected for non-safe tools."""
    role = RoleSpec(
        role_id="reader",
        role_type="worker",
        backend="claude",
        model="opus",
        write_access=False,
    )
    coordinator = _make_coordinator_stub(role_by_agent={"agent-1": role})
    req = _make_request(tool_name="write_file", agent_id="agent-1")
    resp = coordinator._evaluate_permission(req)

    assert resp.decision == "rejected"
    assert "write_access" in resp.reason


def test_unknown_agent_rejected():
    """An agent not present in role_by_agent should be rejected for write tools."""
    coordinator = _make_coordinator_stub(role_by_agent={})
    req = _make_request(tool_name="write_file", agent_id="agent-unknown")
    resp = coordinator._evaluate_permission(req)

    assert resp.decision == "rejected"
