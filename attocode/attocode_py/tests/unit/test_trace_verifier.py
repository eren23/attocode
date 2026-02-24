"""Unit tests for TraceVerifier and create_synthetic_run."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers.fixtures import (
    SyntheticAgent,
    SyntheticRunSpec,
    SyntheticTask,
    _build_healthy_events,
    _ts,
    create_synthetic_run,
)
from tests.helpers.trace_verifier import TraceVerifier


# =============================================================================
# Fixture helpers
# =============================================================================


def _make_verifier(tmp_path: Path, spec: SyntheticRunSpec | None = None) -> TraceVerifier:
    run_dir = create_synthetic_run(tmp_path, spec)
    return TraceVerifier(run_dir)


# =============================================================================
# create_synthetic_run sanity checks
# =============================================================================


class TestCreateSyntheticRun:
    def test_default_creates_valid_layout(self, tmp_path: Path) -> None:
        run_dir = create_synthetic_run(tmp_path)
        assert (run_dir / "swarm.state.json").exists()
        assert (run_dir / "swarm.manifest.json").exists()
        assert (run_dir / "swarm.events.jsonl").exists()
        assert (run_dir / "tasks").is_dir()
        assert (run_dir / "agents").is_dir()

    def test_default_has_two_tasks(self, tmp_path: Path) -> None:
        run_dir = create_synthetic_run(tmp_path)
        task_files = list((run_dir / "tasks").glob("task-*.json"))
        assert len(task_files) == 2

    def test_custom_spec_respected(self, tmp_path: Path) -> None:
        spec = SyntheticRunSpec(
            run_id="run_custom",
            phase="executing",
            agents=[SyntheticAgent(agent_id="x1")],
            tasks=[SyntheticTask(task_id="tx1", status="running")],
            events=[],
        )
        run_dir = create_synthetic_run(tmp_path, spec)
        assert run_dir.name == "run_custom"
        v = TraceVerifier(run_dir)
        assert v.state["phase"] == "executing"
        assert "tx1" in v.tasks


# =============================================================================
# Clean run passes all checks
# =============================================================================


class TestCleanRun:
    def test_all_checks_pass(self, tmp_path: Path) -> None:
        v = _make_verifier(tmp_path)
        results = v.run_all()
        for r in results:
            assert r.passed, f"{r.check} failed: {r.violations}"

    def test_summary_reports_all_passed(self, tmp_path: Path) -> None:
        v = _make_verifier(tmp_path)
        summary = v.summary()
        assert "0 failed" in summary


# =============================================================================
# Poisoned prompt detection
# =============================================================================


class TestPoisonedPrompts:
    def test_task_done_marker_detected(self, tmp_path: Path) -> None:
        agent = SyntheticAgent(agent_id="a1")
        task = SyntheticTask(task_id="t1", status="done", assigned_agent_id="a1")
        events = _build_healthy_events("a1", [task])
        # Inject a poisoned event
        events.append({
            "timestamp": _ts(100),
            "type": "agent.event",
            "payload": {"agent_id": "a1", "task_id": "t1", "message": "Result: [TASK_DONE] success"},
        })
        spec = SyntheticRunSpec(agents=[agent], tasks=[task], events=events)
        v = _make_verifier(tmp_path, spec)

        result = v.assert_no_poisoned_prompts()
        assert not result.passed
        assert any("[TASK_DONE]" in v for v in result.violations)

    def test_heartbeat_marker_detected(self, tmp_path: Path) -> None:
        agent = SyntheticAgent(agent_id="a1")
        task = SyntheticTask(task_id="t1", status="done", assigned_agent_id="a1")
        events = _build_healthy_events("a1", [task])
        events.append({
            "timestamp": _ts(100),
            "type": "agent.event",
            "payload": {"agent_id": "a1", "task_id": "t1", "message": "[HEARTBEAT] alive"},
        })
        spec = SyntheticRunSpec(agents=[agent], tasks=[task], events=events)
        v = _make_verifier(tmp_path, spec)

        result = v.assert_no_poisoned_prompts()
        assert not result.passed

    def test_clean_messages_pass(self, tmp_path: Path) -> None:
        v = _make_verifier(tmp_path)
        result = v.assert_no_poisoned_prompts()
        assert result.passed


# =============================================================================
# Task transition validation
# =============================================================================


class TestTaskTransitions:
    def test_illegal_done_to_running(self, tmp_path: Path) -> None:
        agent = SyntheticAgent(agent_id="a1")
        task = SyntheticTask(task_id="t1", status="done", assigned_agent_id="a1")
        events = _build_healthy_events("a1", [task])
        # Inject illegal transition: done -> running
        events.append({
            "timestamp": _ts(100),
            "type": "task.transition",
            "payload": {"task_id": "t1", "from_state": "done", "to_state": "running", "reason": "retry"},
        })
        spec = SyntheticRunSpec(agents=[agent], tasks=[task], events=events)
        v = _make_verifier(tmp_path, spec)

        result = v.assert_correct_task_transitions()
        assert not result.passed
        assert any("done" in v and "running" in v for v in result.violations)

    def test_unknown_state(self, tmp_path: Path) -> None:
        agent = SyntheticAgent(agent_id="a1")
        task = SyntheticTask(task_id="t1", status="done", assigned_agent_id="a1")
        events = _build_healthy_events("a1", [task])
        events.append({
            "timestamp": _ts(100),
            "type": "task.transition",
            "payload": {"task_id": "t1", "from_state": "bogus", "to_state": "running", "reason": "?"},
        })
        spec = SyntheticRunSpec(agents=[agent], tasks=[task], events=events)
        v = _make_verifier(tmp_path, spec)

        result = v.assert_correct_task_transitions()
        assert not result.passed

    def test_valid_transitions_pass(self, tmp_path: Path) -> None:
        v = _make_verifier(tmp_path)
        result = v.assert_correct_task_transitions()
        assert result.passed


# =============================================================================
# Terminal events
# =============================================================================


class TestTerminalEvents:
    def test_missing_exit_event(self, tmp_path: Path) -> None:
        agent = SyntheticAgent(agent_id="a1")
        task = SyntheticTask(task_id="t1", status="done", assigned_agent_id="a1")
        # Build events but strip the exit event
        events = [
            e for e in _build_healthy_events("a1", [task])
            if e.get("type") != "agent.task.exit"
        ]
        spec = SyntheticRunSpec(agents=[agent], tasks=[task], events=events)
        v = _make_verifier(tmp_path, spec)

        result = v.assert_all_tasks_have_terminal_events()
        assert not result.passed
        assert any("agent.task.exit" in v for v in result.violations)

    def test_missing_classified_event(self, tmp_path: Path) -> None:
        agent = SyntheticAgent(agent_id="a1")
        task = SyntheticTask(task_id="t1", status="done", assigned_agent_id="a1")
        events = [
            e for e in _build_healthy_events("a1", [task])
            if e.get("type") != "agent.task.classified"
        ]
        spec = SyntheticRunSpec(agents=[agent], tasks=[task], events=events)
        v = _make_verifier(tmp_path, spec)

        result = v.assert_all_tasks_have_terminal_events()
        assert not result.passed
        assert any("agent.task.classified" in v for v in result.violations)


# =============================================================================
# Stuck agents
# =============================================================================


class TestStuckAgents:
    def test_large_gap_detected(self, tmp_path: Path) -> None:
        agent = SyntheticAgent(agent_id="a1")
        task = SyntheticTask(task_id="t1", status="done", assigned_agent_id="a1")
        events = _build_healthy_events("a1", [task])
        # Add events with a 60s gap
        events.append({
            "timestamp": _ts(200),
            "type": "agent.event",
            "payload": {"agent_id": "a1", "task_id": "t1", "message": "first"},
        })
        events.append({
            "timestamp": _ts(261),
            "type": "agent.event",
            "payload": {"agent_id": "a1", "task_id": "t1", "message": "second after gap"},
        })
        spec = SyntheticRunSpec(agents=[agent], tasks=[task], events=events)
        v = _make_verifier(tmp_path, spec)

        result = v.assert_no_stuck_agents(max_gap_seconds=30.0)
        assert not result.passed
        assert any("gap" in v.lower() for v in result.violations)

    def test_normal_gaps_pass(self, tmp_path: Path) -> None:
        v = _make_verifier(tmp_path)
        result = v.assert_no_stuck_agents()
        assert result.passed


# =============================================================================
# Budget limits
# =============================================================================


class TestBudgetLimits:
    def test_token_overrun(self, tmp_path: Path) -> None:
        spec = SyntheticRunSpec(
            agents=[SyntheticAgent(agent_id="a1")],
            tasks=[SyntheticTask(task_id="t1", status="done", assigned_agent_id="a1")],
            events=_build_healthy_events("a1", [SyntheticTask(task_id="t1", status="done")]),
            budget_tokens_used=6_000_000,
            budget_tokens_max=5_000_000,
        )
        v = _make_verifier(tmp_path, spec)

        result = v.assert_budget_within_limits()
        assert not result.passed
        assert any("tokens" in v for v in result.violations)

    def test_cost_overrun(self, tmp_path: Path) -> None:
        spec = SyntheticRunSpec(
            agents=[SyntheticAgent(agent_id="a1")],
            tasks=[SyntheticTask(task_id="t1", status="done", assigned_agent_id="a1")],
            events=_build_healthy_events("a1", [SyntheticTask(task_id="t1", status="done")]),
            budget_cost_used=30.0,
            budget_cost_max=25.0,
        )
        v = _make_verifier(tmp_path, spec)

        result = v.assert_budget_within_limits()
        assert not result.passed
        assert any("cost" in v for v in result.violations)

    def test_within_limits_pass(self, tmp_path: Path) -> None:
        v = _make_verifier(tmp_path)
        result = v.assert_budget_within_limits()
        assert result.passed


# =============================================================================
# Exit code propagation
# =============================================================================


class TestExitCodePropagation:
    def test_dangling_running_task(self, tmp_path: Path) -> None:
        # Agent has exit_code but task is still "running" in the DAG
        agent = SyntheticAgent(agent_id="a1", exit_code=1, status="exited")
        task = SyntheticTask(task_id="t1", status="running", assigned_agent_id="a1")
        spec = SyntheticRunSpec(
            agents=[agent],
            tasks=[task],
            events=[],
        )
        v = _make_verifier(tmp_path, spec)

        result = v.assert_exit_codes_propagated()
        assert not result.passed
        assert any("running" in v and "exit_code" in v for v in result.violations)

    def test_properly_propagated_pass(self, tmp_path: Path) -> None:
        v = _make_verifier(tmp_path)
        result = v.assert_exit_codes_propagated()
        assert result.passed


# =============================================================================
# Coding task output
# =============================================================================


class TestCodingTaskOutput:
    def test_implement_task_no_file_evidence(self, tmp_path: Path) -> None:
        agent = SyntheticAgent(agent_id="a1")
        task = SyntheticTask(task_id="t1", title="Build API", task_kind="implement", status="done", assigned_agent_id="a1")
        events = _build_healthy_events("a1", [task])
        # Replace agent.event messages with non-file-related text
        for ev in events:
            if ev.get("type") == "agent.event":
                ev["payload"]["message"] = "Thinking about architecture..."
        spec = SyntheticRunSpec(agents=[agent], tasks=[task], events=events)
        v = _make_verifier(tmp_path, spec)

        result = v.assert_coding_tasks_produced_output()
        assert not result.passed

    def test_implement_with_file_ops_pass(self, tmp_path: Path) -> None:
        agent = SyntheticAgent(agent_id="a1")
        task = SyntheticTask(task_id="t1", title="Build API", task_kind="implement", status="done", assigned_agent_id="a1")
        events = _build_healthy_events("a1", [task])
        # Ensure at least one event has file evidence
        for ev in events:
            if ev.get("type") == "agent.event":
                ev["payload"]["message"] = "Created src/api.py with write_file"
                break
        spec = SyntheticRunSpec(agents=[agent], tasks=[task], events=events)
        v = _make_verifier(tmp_path, spec)

        result = v.assert_coding_tasks_produced_output()
        assert result.passed

    def test_non_coding_task_skipped(self, tmp_path: Path) -> None:
        """Tasks with kind != implement/test/integrate are not checked."""
        agent = SyntheticAgent(agent_id="a1")
        task = SyntheticTask(task_id="t1", task_kind="design", status="done", assigned_agent_id="a1")
        events = _build_healthy_events("a1", [task])
        for ev in events:
            if ev.get("type") == "agent.event":
                ev["payload"]["message"] = "Thinking..."
        spec = SyntheticRunSpec(agents=[agent], tasks=[task], events=events)
        v = _make_verifier(tmp_path, spec)

        result = v.assert_coding_tasks_produced_output()
        assert result.passed  # design tasks are not checked
