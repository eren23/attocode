"""Comprehensive tests for the delegation protocol module."""

import pytest

from attocode.integrations.agents.delegation import (
    DelegationProtocol,
    DelegationRequest,
    DelegationResult,
    DelegationStatus,
)


# ---------------------------------------------------------------------------
# Data classes & enum
# ---------------------------------------------------------------------------


class TestDelegationStatus:
    def test_enum_values(self):
        assert DelegationStatus.PENDING == "pending"
        assert DelegationStatus.ACCEPTED == "accepted"
        assert DelegationStatus.IN_PROGRESS == "in_progress"
        assert DelegationStatus.COMPLETED == "completed"
        assert DelegationStatus.FAILED == "failed"
        assert DelegationStatus.REJECTED == "rejected"

    def test_enum_membership(self):
        assert len(DelegationStatus) == 6

    def test_is_str(self):
        """DelegationStatus inherits from StrEnum so values are plain strings."""
        for member in DelegationStatus:
            assert isinstance(member, str)


class TestDelegationRequest:
    def test_required_fields(self):
        req = DelegationRequest(
            task_id="t-1",
            description="Build feature X",
            delegator="agent-root",
        )
        assert req.task_id == "t-1"
        assert req.description == "Build feature X"
        assert req.delegator == "agent-root"

    def test_defaults(self):
        req = DelegationRequest(
            task_id="t-2",
            description="Fix bug",
            delegator="root",
        )
        assert req.delegate is None
        assert req.agent_type is None
        assert req.tools is None
        assert req.context == ""
        assert req.max_iterations == 30
        assert req.priority == 2
        assert req.metadata == {}

    def test_custom_fields(self):
        req = DelegationRequest(
            task_id="t-3",
            description="Research topic",
            delegator="root",
            delegate="agent-researcher",
            agent_type="researcher",
            tools=["search", "read_file"],
            context="Focus on performance",
            max_iterations=10,
            priority=1,
            metadata={"source": "planner"},
        )
        assert req.delegate == "agent-researcher"
        assert req.agent_type == "researcher"
        assert req.tools == ["search", "read_file"]
        assert req.context == "Focus on performance"
        assert req.max_iterations == 10
        assert req.priority == 1
        assert req.metadata == {"source": "planner"}

    def test_metadata_default_factory_independence(self):
        """Each instance gets its own metadata dict."""
        r1 = DelegationRequest(task_id="a", description="d", delegator="x")
        r2 = DelegationRequest(task_id="b", description="d", delegator="x")
        r1.metadata["key"] = "value"
        assert "key" not in r2.metadata


class TestDelegationResult:
    def test_required_fields(self):
        res = DelegationResult(
            task_id="t-1",
            status=DelegationStatus.COMPLETED,
            delegate="worker-1",
        )
        assert res.task_id == "t-1"
        assert res.status == DelegationStatus.COMPLETED
        assert res.delegate == "worker-1"

    def test_defaults(self):
        res = DelegationResult(
            task_id="t-1",
            status=DelegationStatus.COMPLETED,
            delegate="w-1",
        )
        assert res.response == ""
        assert res.error is None
        assert res.tokens_used == 0
        assert res.duration_ms == 0.0
        assert res.artifacts == {}

    def test_custom_fields(self):
        res = DelegationResult(
            task_id="t-1",
            status=DelegationStatus.FAILED,
            delegate="w-1",
            response="partial output",
            error="OOM",
            tokens_used=1500,
            duration_ms=4200.5,
            artifacts={"log": "trace.jsonl"},
        )
        assert res.response == "partial output"
        assert res.error == "OOM"
        assert res.tokens_used == 1500
        assert res.duration_ms == 4200.5
        assert res.artifacts == {"log": "trace.jsonl"}

    def test_artifacts_default_factory_independence(self):
        r1 = DelegationResult(
            task_id="a", status=DelegationStatus.COMPLETED, delegate="w"
        )
        r2 = DelegationResult(
            task_id="b", status=DelegationStatus.COMPLETED, delegate="w"
        )
        r1.artifacts["k"] = "v"
        assert "k" not in r2.artifacts


# ---------------------------------------------------------------------------
# DelegationProtocol
# ---------------------------------------------------------------------------


class TestDelegationProtocolSubmit:
    def test_submit_returns_task_id(self):
        proto = DelegationProtocol()
        req = DelegationRequest(task_id="t-1", description="d", delegator="root")
        tid = proto.submit(req)
        assert tid == "t-1"

    def test_submit_stores_request(self):
        proto = DelegationProtocol()
        req = DelegationRequest(task_id="t-1", description="d", delegator="root")
        proto.submit(req)
        stored = proto.get_request("t-1")
        assert stored is req

    def test_submit_overwrites_duplicate_task_id(self):
        proto = DelegationProtocol()
        r1 = DelegationRequest(task_id="t-1", description="first", delegator="root")
        r2 = DelegationRequest(task_id="t-1", description="second", delegator="root")
        proto.submit(r1)
        proto.submit(r2)
        assert proto.get_request("t-1").description == "second"


class TestDelegationProtocolGetRequest:
    def test_get_existing_request(self):
        proto = DelegationProtocol()
        req = DelegationRequest(task_id="t-1", description="d", delegator="root")
        proto.submit(req)
        assert proto.get_request("t-1") is req

    def test_get_nonexistent_request(self):
        proto = DelegationProtocol()
        assert proto.get_request("no-such-task") is None


class TestDelegationProtocolAccept:
    def test_accept_existing_request(self):
        proto = DelegationProtocol()
        req = DelegationRequest(task_id="t-1", description="d", delegator="root")
        proto.submit(req)
        result = proto.accept("t-1", "worker-1")
        assert result is True

    def test_accept_stores_delegate_in_active(self):
        proto = DelegationProtocol()
        req = DelegationRequest(task_id="t-1", description="d", delegator="root")
        proto.submit(req)
        proto.accept("t-1", "worker-1")
        active = proto.get_active()
        assert len(active) == 1
        assert active[0] == (req, "worker-1")

    def test_accept_nonexistent_task_returns_false(self):
        proto = DelegationProtocol()
        result = proto.accept("no-such-task", "worker-1")
        assert result is False

    def test_accept_does_not_add_to_active_when_missing(self):
        proto = DelegationProtocol()
        proto.accept("no-such-task", "worker-1")
        assert proto.get_active() == []

    def test_accept_same_task_twice_updates_delegate(self):
        proto = DelegationProtocol()
        req = DelegationRequest(task_id="t-1", description="d", delegator="root")
        proto.submit(req)
        proto.accept("t-1", "worker-1")
        proto.accept("t-1", "worker-2")
        active = proto.get_active()
        assert len(active) == 1
        assert active[0][1] == "worker-2"


class TestDelegationProtocolComplete:
    def test_complete_stores_result(self):
        proto = DelegationProtocol()
        req = DelegationRequest(task_id="t-1", description="d", delegator="root")
        proto.submit(req)
        proto.accept("t-1", "w-1")
        res = DelegationResult(
            task_id="t-1",
            status=DelegationStatus.COMPLETED,
            delegate="w-1",
            response="All done",
        )
        proto.complete(res)
        assert proto.get_result("t-1") is res

    def test_complete_removes_from_active(self):
        proto = DelegationProtocol()
        req = DelegationRequest(task_id="t-1", description="d", delegator="root")
        proto.submit(req)
        proto.accept("t-1", "w-1")
        res = DelegationResult(
            task_id="t-1",
            status=DelegationStatus.COMPLETED,
            delegate="w-1",
        )
        proto.complete(res)
        assert proto.get_active() == []

    def test_complete_already_completed_overwrites(self):
        proto = DelegationProtocol()
        req = DelegationRequest(task_id="t-1", description="d", delegator="root")
        proto.submit(req)
        r1 = DelegationResult(
            task_id="t-1",
            status=DelegationStatus.COMPLETED,
            delegate="w-1",
            response="first",
        )
        r2 = DelegationResult(
            task_id="t-1",
            status=DelegationStatus.COMPLETED,
            delegate="w-1",
            response="second",
        )
        proto.complete(r1)
        proto.complete(r2)
        assert proto.get_result("t-1").response == "second"

    def test_complete_without_prior_accept(self):
        """Completing a task that was never accepted still stores the result."""
        proto = DelegationProtocol()
        req = DelegationRequest(task_id="t-1", description="d", delegator="root")
        proto.submit(req)
        res = DelegationResult(
            task_id="t-1",
            status=DelegationStatus.COMPLETED,
            delegate="w-1",
        )
        proto.complete(res)
        assert proto.get_result("t-1") is res

    def test_complete_unknown_task_still_stores(self):
        """Completing a task that was never submitted still stores the result."""
        proto = DelegationProtocol()
        res = DelegationResult(
            task_id="unknown",
            status=DelegationStatus.COMPLETED,
            delegate="w-1",
        )
        proto.complete(res)
        assert proto.get_result("unknown") is res


class TestDelegationProtocolGetResult:
    def test_get_existing_result(self):
        proto = DelegationProtocol()
        res = DelegationResult(
            task_id="t-1",
            status=DelegationStatus.COMPLETED,
            delegate="w-1",
        )
        proto.complete(res)
        assert proto.get_result("t-1") is res

    def test_get_nonexistent_result(self):
        proto = DelegationProtocol()
        assert proto.get_result("nope") is None


class TestDelegationProtocolGetPending:
    def test_empty_protocol_returns_empty(self):
        proto = DelegationProtocol()
        assert proto.get_pending() == []

    def test_submitted_request_is_pending(self):
        proto = DelegationProtocol()
        req = DelegationRequest(task_id="t-1", description="d", delegator="root")
        proto.submit(req)
        pending = proto.get_pending()
        assert len(pending) == 1
        assert pending[0] is req

    def test_accepted_request_not_pending(self):
        proto = DelegationProtocol()
        req = DelegationRequest(task_id="t-1", description="d", delegator="root")
        proto.submit(req)
        proto.accept("t-1", "w-1")
        assert proto.get_pending() == []

    def test_completed_request_not_pending(self):
        proto = DelegationProtocol()
        req = DelegationRequest(task_id="t-1", description="d", delegator="root")
        proto.submit(req)
        res = DelegationResult(
            task_id="t-1",
            status=DelegationStatus.COMPLETED,
            delegate="w-1",
        )
        proto.complete(res)
        assert proto.get_pending() == []

    def test_multiple_pending(self):
        proto = DelegationProtocol()
        for i in range(3):
            proto.submit(
                DelegationRequest(
                    task_id=f"t-{i}",
                    description=f"task {i}",
                    delegator="root",
                )
            )
        proto.accept("t-1", "w-1")
        pending = proto.get_pending()
        ids = {r.task_id for r in pending}
        assert ids == {"t-0", "t-2"}

    def test_cancelled_request_not_pending(self):
        """Once cancelled (result stored), the request is no longer pending."""
        proto = DelegationProtocol()
        req = DelegationRequest(task_id="t-1", description="d", delegator="root")
        proto.submit(req)
        proto.cancel("t-1")
        assert proto.get_pending() == []


class TestDelegationProtocolGetActive:
    def test_empty_returns_empty(self):
        proto = DelegationProtocol()
        assert proto.get_active() == []

    def test_accepted_task_is_active(self):
        proto = DelegationProtocol()
        req = DelegationRequest(task_id="t-1", description="d", delegator="root")
        proto.submit(req)
        proto.accept("t-1", "w-1")
        active = proto.get_active()
        assert len(active) == 1
        assert active[0] == (req, "w-1")

    def test_completed_task_not_active(self):
        proto = DelegationProtocol()
        req = DelegationRequest(task_id="t-1", description="d", delegator="root")
        proto.submit(req)
        proto.accept("t-1", "w-1")
        proto.complete(
            DelegationResult(
                task_id="t-1",
                status=DelegationStatus.COMPLETED,
                delegate="w-1",
            )
        )
        assert proto.get_active() == []

    def test_multiple_active(self):
        proto = DelegationProtocol()
        for i in range(3):
            proto.submit(
                DelegationRequest(
                    task_id=f"t-{i}",
                    description=f"task {i}",
                    delegator="root",
                )
            )
            proto.accept(f"t-{i}", f"w-{i}")
        active = proto.get_active()
        assert len(active) == 3
        delegates = {d for _, d in active}
        assert delegates == {"w-0", "w-1", "w-2"}

    def test_pending_task_not_active(self):
        proto = DelegationProtocol()
        proto.submit(
            DelegationRequest(task_id="t-1", description="d", delegator="root")
        )
        assert proto.get_active() == []


class TestDelegationProtocolGetAgentDelegations:
    def test_empty(self):
        proto = DelegationProtocol()
        assert proto.get_agent_delegations("w-1") == []

    def test_returns_tasks_for_specific_agent(self):
        proto = DelegationProtocol()
        r1 = DelegationRequest(task_id="t-1", description="d1", delegator="root")
        r2 = DelegationRequest(task_id="t-2", description="d2", delegator="root")
        r3 = DelegationRequest(task_id="t-3", description="d3", delegator="root")
        proto.submit(r1)
        proto.submit(r2)
        proto.submit(r3)
        proto.accept("t-1", "w-1")
        proto.accept("t-2", "w-2")
        proto.accept("t-3", "w-1")
        w1_tasks = proto.get_agent_delegations("w-1")
        ids = {r.task_id for r in w1_tasks}
        assert ids == {"t-1", "t-3"}

    def test_no_match_returns_empty(self):
        proto = DelegationProtocol()
        proto.submit(
            DelegationRequest(task_id="t-1", description="d", delegator="root")
        )
        proto.accept("t-1", "w-1")
        assert proto.get_agent_delegations("w-99") == []

    def test_completed_task_not_in_agent_delegations(self):
        """Completed tasks are removed from active, so they should not appear."""
        proto = DelegationProtocol()
        req = DelegationRequest(task_id="t-1", description="d", delegator="root")
        proto.submit(req)
        proto.accept("t-1", "w-1")
        proto.complete(
            DelegationResult(
                task_id="t-1",
                status=DelegationStatus.COMPLETED,
                delegate="w-1",
            )
        )
        assert proto.get_agent_delegations("w-1") == []


class TestDelegationProtocolCancel:
    def test_cancel_submitted_request(self):
        proto = DelegationProtocol()
        proto.submit(
            DelegationRequest(task_id="t-1", description="d", delegator="root")
        )
        result = proto.cancel("t-1")
        assert result is True

    def test_cancel_stores_rejected_result(self):
        proto = DelegationProtocol()
        proto.submit(
            DelegationRequest(task_id="t-1", description="d", delegator="root")
        )
        proto.cancel("t-1")
        res = proto.get_result("t-1")
        assert res is not None
        assert res.status == DelegationStatus.REJECTED
        assert res.delegate == ""
        assert res.error == "Cancelled"

    def test_cancel_active_removes_from_active(self):
        proto = DelegationProtocol()
        proto.submit(
            DelegationRequest(task_id="t-1", description="d", delegator="root")
        )
        proto.accept("t-1", "w-1")
        proto.cancel("t-1")
        assert proto.get_active() == []

    def test_cancel_nonexistent_returns_false(self):
        proto = DelegationProtocol()
        assert proto.cancel("no-such-task") is False

    def test_cancel_nonexistent_does_not_store_result(self):
        proto = DelegationProtocol()
        proto.cancel("no-such-task")
        assert proto.get_result("no-such-task") is None

    def test_cancel_already_completed_overwrites_result(self):
        """Cancel can overwrite a previous result since the request exists."""
        proto = DelegationProtocol()
        proto.submit(
            DelegationRequest(task_id="t-1", description="d", delegator="root")
        )
        proto.complete(
            DelegationResult(
                task_id="t-1",
                status=DelegationStatus.COMPLETED,
                delegate="w-1",
                response="done",
            )
        )
        proto.cancel("t-1")
        res = proto.get_result("t-1")
        assert res.status == DelegationStatus.REJECTED


class TestDelegationProtocolClear:
    def test_clear_empties_all_state(self):
        proto = DelegationProtocol()
        proto.submit(
            DelegationRequest(task_id="t-1", description="d", delegator="root")
        )
        proto.accept("t-1", "w-1")
        proto.complete(
            DelegationResult(
                task_id="t-1",
                status=DelegationStatus.COMPLETED,
                delegate="w-1",
            )
        )
        proto.submit(
            DelegationRequest(task_id="t-2", description="d2", delegator="root")
        )
        proto.clear()
        assert proto.get_request("t-1") is None
        assert proto.get_result("t-1") is None
        assert proto.get_active() == []
        assert proto.get_pending() == []

    def test_clear_then_reuse(self):
        proto = DelegationProtocol()
        proto.submit(
            DelegationRequest(task_id="t-1", description="d", delegator="root")
        )
        proto.clear()
        proto.submit(
            DelegationRequest(task_id="t-2", description="new", delegator="root")
        )
        assert proto.get_request("t-2") is not None
        assert proto.get_request("t-1") is None


# ---------------------------------------------------------------------------
# Integration / lifecycle flows
# ---------------------------------------------------------------------------


class TestDelegationProtocolLifecycle:
    """End-to-end scenarios exercising the full delegation lifecycle."""

    def test_full_lifecycle_submit_accept_complete(self):
        proto = DelegationProtocol()
        req = DelegationRequest(
            task_id="t-1",
            description="Implement parser",
            delegator="orchestrator",
            delegate="coder-1",
            priority=1,
        )
        tid = proto.submit(req)
        assert proto.get_pending() == [req]
        assert proto.get_active() == []

        proto.accept(tid, "coder-1")
        assert proto.get_pending() == []
        assert len(proto.get_active()) == 1
        assert proto.get_agent_delegations("coder-1") == [req]

        result = DelegationResult(
            task_id=tid,
            status=DelegationStatus.COMPLETED,
            delegate="coder-1",
            response="Parser implemented",
            tokens_used=5000,
            duration_ms=12000.0,
        )
        proto.complete(result)
        assert proto.get_pending() == []
        assert proto.get_active() == []
        assert proto.get_agent_delegations("coder-1") == []
        assert proto.get_result(tid) is result

    def test_submit_then_cancel(self):
        proto = DelegationProtocol()
        proto.submit(
            DelegationRequest(task_id="t-1", description="d", delegator="root")
        )
        assert len(proto.get_pending()) == 1
        proto.cancel("t-1")
        assert proto.get_pending() == []
        res = proto.get_result("t-1")
        assert res.status == DelegationStatus.REJECTED

    def test_accept_then_cancel(self):
        proto = DelegationProtocol()
        proto.submit(
            DelegationRequest(task_id="t-1", description="d", delegator="root")
        )
        proto.accept("t-1", "w-1")
        assert len(proto.get_active()) == 1
        proto.cancel("t-1")
        assert proto.get_active() == []
        assert proto.get_result("t-1").status == DelegationStatus.REJECTED

    def test_mixed_states(self):
        """Multiple tasks in different states at the same time."""
        proto = DelegationProtocol()
        for i in range(5):
            proto.submit(
                DelegationRequest(
                    task_id=f"t-{i}",
                    description=f"task {i}",
                    delegator="root",
                )
            )

        # t-0: pending
        # t-1: accepted (active)
        proto.accept("t-1", "w-1")
        # t-2: completed
        proto.accept("t-2", "w-2")
        proto.complete(
            DelegationResult(
                task_id="t-2",
                status=DelegationStatus.COMPLETED,
                delegate="w-2",
            )
        )
        # t-3: cancelled
        proto.cancel("t-3")
        # t-4: pending

        pending_ids = {r.task_id for r in proto.get_pending()}
        assert pending_ids == {"t-0", "t-4"}

        active = proto.get_active()
        assert len(active) == 1
        assert active[0][1] == "w-1"

        assert proto.get_result("t-2").status == DelegationStatus.COMPLETED
        assert proto.get_result("t-3").status == DelegationStatus.REJECTED
        assert proto.get_result("t-0") is None
