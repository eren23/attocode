"""Tests for agents, tasks, skills, and mcp integrations."""

from __future__ import annotations

import pytest
from pathlib import Path
from typing import Any

# agents
from attocode.integrations.agents.blackboard import SharedBlackboard
from attocode.integrations.agents.registry import (
    BUILTIN_AGENTS,
    AgentDefinition,
    AgentRegistry,
)
from attocode.integrations.agents.delegation import (
    DelegationProtocol,
    DelegationRequest,
    DelegationResult,
    DelegationStatus,
)

# tasks
from attocode.integrations.tasks.task_manager import TaskManager
from attocode.integrations.tasks.work_log import WorkEntryType, WorkLog
from attocode.integrations.tasks.decomposer import (
    ComplexityTier,
    classify_complexity,
    decompose_simple,
)
from attocode.types.agent import PlanTask, TaskStatus

# skills
from attocode.integrations.skills.loader import SkillLoader, _parse_skill_content
from attocode.integrations.skills.executor import SkillExecutor

# mcp
from attocode.integrations.mcp.client import MCPCallResult, MCPClient, MCPTool


class TestSharedBlackboard:
    @pytest.fixture()
    def bb(self) -> SharedBlackboard:
        return SharedBlackboard()

    def test_publish_and_get(self, bb: SharedBlackboard) -> None:
        bb.publish("key1", "value1", owner="agent-a")
        assert bb.get("key1") == "value1"

    def test_get_missing_returns_default(self, bb: SharedBlackboard) -> None:
        assert bb.get("nope") is None
        assert bb.get("nope", 42) == 42

    def test_has(self, bb: SharedBlackboard) -> None:
        assert not bb.has("k")
        bb.publish("k", 1)
        assert bb.has("k")

    def test_remove(self, bb: SharedBlackboard) -> None:
        bb.publish("x", 10, owner="a")
        assert bb.remove("x")
        assert not bb.has("x")
        assert not bb.remove("x")

    def test_remove_clears_agent_tracking(self, bb: SharedBlackboard) -> None:
        bb.publish("x", 10, owner="agent-a")
        bb.remove("x")
        assert bb.get_agent_keys("agent-a") == []

    def test_keys_and_items(self, bb: SharedBlackboard) -> None:
        bb.publish("a", 1)
        bb.publish("b", 2)
        assert set(bb.keys()) == {"a", "b"}
        items = dict(bb.items())
        assert items == {"a": 1, "b": 2}

    def test_subscribe_to_key(self, bb: SharedBlackboard) -> None:
        received: list[tuple[str, Any, str]] = []
        bb.subscribe("color", lambda k, v, o: received.append((k, v, o)), subscriber_id="s1")
        bb.publish("color", "red", owner="agent-a")
        assert len(received) == 1
        assert received[0] == ("color", "red", "agent-a")

    def test_subscribe_to_key_unsubscribe(self, bb: SharedBlackboard) -> None:
        received: list[Any] = []
        unsub = bb.subscribe("color", lambda k, v, o: received.append(v))
        bb.publish("color", "red")
        unsub()
        bb.publish("color", "blue")
        assert received == ["red"]

    def test_subscribe_all(self, bb: SharedBlackboard) -> None:
        received: list[str] = []
        bb.subscribe_all(lambda k, v, o: received.append(k), subscriber_id="g1")
        bb.publish("a", 1)
        bb.publish("b", 2)
        assert received == ["a", "b"]

    def test_subscribe_all_unsubscribe(self, bb: SharedBlackboard) -> None:
        received: list[str] = []
        unsub = bb.subscribe_all(lambda k, v, o: received.append(k))
        bb.publish("a", 1)
        unsub()
        bb.publish("b", 2)
        assert received == ["a"]

    def test_subscriber_notifications_on_publish(self, bb: SharedBlackboard) -> None:
        key_events: list[str] = []
        global_events: list[str] = []
        bb.subscribe("data", lambda k, v, o: key_events.append(f"{k}={v}"))
        bb.subscribe_all(lambda k, v, o: global_events.append(f"{k}={v}"))
        bb.publish("data", 42)
        assert key_events == ["data=42"]
        assert global_events == ["data=42"]

    def test_subscriber_exception_does_not_propagate(self, bb: SharedBlackboard) -> None:
        def bad_cb(k: str, v: Any, o: str) -> None:
            raise RuntimeError("boom")
        bb.subscribe("k", bad_cb)
        bb.publish("k", "val")
        assert bb.get("k") == "val"

    def test_release_all(self, bb: SharedBlackboard) -> None:
        bb.publish("a", 1, owner="agent-x")
        bb.publish("b", 2, owner="agent-x")
        bb.publish("c", 3, owner="agent-y")
        removed = bb.release_all("agent-x")
        assert removed == 2
        assert not bb.has("a")
        assert not bb.has("b")
        assert bb.has("c")

    def test_release_all_unknown_owner(self, bb: SharedBlackboard) -> None:
        assert bb.release_all("nobody") == 0

    def test_unsubscribe_agent(self, bb: SharedBlackboard) -> None:
        received: list[str] = []
        bb.subscribe("x", lambda k, v, o: received.append("key"), subscriber_id="agent-a")
        bb.subscribe_all(lambda k, v, o: received.append("global"), subscriber_id="agent-a")
        bb.unsubscribe_agent("agent-a")
        bb.publish("x", 1)
        assert received == []

    def test_get_agent_keys(self, bb: SharedBlackboard) -> None:
        bb.publish("m", 1, owner="agent-1")
        bb.publish("n", 2, owner="agent-1")
        bb.publish("o", 3, owner="agent-2")
        keys = set(bb.get_agent_keys("agent-1"))
        assert keys == {"m", "n"}
        assert bb.get_agent_keys("agent-2") == ["o"]
        assert bb.get_agent_keys("agent-3") == []

    def test_clear(self, bb: SharedBlackboard) -> None:
        bb.publish("a", 1)
        bb.subscribe("a", lambda k, v, o: None)
        bb.subscribe_all(lambda k, v, o: None)
        bb.clear()
        assert bb.keys() == []
        bb.publish("b", 2)
        assert bb.get("b") == 2

    def test_snapshot(self, bb: SharedBlackboard) -> None:
        bb.publish("x", 10)
        bb.publish("y", 20)
        snap = bb.snapshot()
        assert snap == {"x": 10, "y": 20}
        snap["x"] = 999
        assert bb.get("x") == 10

    def test_overwrite_key_updates_owner(self, bb: SharedBlackboard) -> None:
        bb.publish("key", 1, owner="a")
        bb.publish("key", 2, owner="b")
        assert bb.get("key") == 2
        assert "key" in bb.get_agent_keys("b")


class TestAgentRegistry:
    def test_builtin_agents_exist(self) -> None:
        assert "coder" in BUILTIN_AGENTS
        assert "researcher" in BUILTIN_AGENTS
        assert "reviewer" in BUILTIN_AGENTS

    def test_builtin_agents_have_descriptions(self) -> None:
        for name, agent in BUILTIN_AGENTS.items():
            assert agent.description, f"{name} missing description"

    def test_load_populates_builtins(self, tmp_path: Path) -> None:
        registry = AgentRegistry(project_root=tmp_path)
        registry.load()
        assert registry.has("coder")
        assert registry.has("researcher")
        assert registry.has("reviewer")

    def test_get_returns_definition(self, tmp_path: Path) -> None:
        registry = AgentRegistry(project_root=tmp_path)
        registry.load()
        coder = registry.get("coder")
        assert coder is not None
        assert coder.name == "coder"

    def test_get_missing_returns_none(self, tmp_path: Path) -> None:
        registry = AgentRegistry(project_root=tmp_path)
        registry.load()
        assert registry.get("nonexistent") is None

    def test_has_works(self, tmp_path: Path) -> None:
        registry = AgentRegistry(project_root=tmp_path)
        registry.load()
        assert registry.has("coder")
        assert not registry.has("nonexistent")

    def test_register_custom_agent(self, tmp_path: Path) -> None:
        registry = AgentRegistry(project_root=tmp_path)
        registry.load()
        custom = AgentDefinition(name="my-agent", description="Custom agent")
        registry.register(custom)
        assert registry.has("my-agent")
        assert registry.get("my-agent") is custom

    def test_list_agents_returns_all(self, tmp_path: Path) -> None:
        registry = AgentRegistry(project_root=tmp_path)
        registry.load()
        agents = registry.list_agents()
        names = {a.name for a in agents}
        assert {"coder", "researcher", "reviewer"} <= names

    def test_auto_load_on_get(self, tmp_path: Path) -> None:
        registry = AgentRegistry(project_root=tmp_path)
        result = registry.get("coder")
        assert result is not None

    def test_load_from_project_yaml(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / ".attocode" / "agents" / "deployer"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AGENT.yaml").write_text(
            "name: deployer\ndescription: Deploy agent\nmodel: gpt-4o\n"
        )
        registry = AgentRegistry(project_root=tmp_path)
        registry.load()
        deployer = registry.get("deployer")
        assert deployer is not None
        assert deployer.description == "Deploy agent"
        assert deployer.model == "gpt-4o"
        assert deployer.source == "project"


class TestDelegationProtocol:
    @pytest.fixture()
    def proto(self) -> DelegationProtocol:
        return DelegationProtocol()

    def _make_request(
        self, task_id: str = "t-1", delegator: str = "orchestrator"
    ) -> DelegationRequest:
        return DelegationRequest(
            task_id=task_id,
            description="Implement feature X",
            delegator=delegator,
        )

    def test_submit_returns_task_id(self, proto: DelegationProtocol) -> None:
        req = self._make_request()
        assert proto.submit(req) == "t-1"

    def test_accept(self, proto: DelegationProtocol) -> None:
        proto.submit(self._make_request())
        assert proto.accept("t-1", "worker-a")

    def test_accept_missing_returns_false(self, proto: DelegationProtocol) -> None:
        assert not proto.accept("missing", "worker-a")

    def test_complete(self, proto: DelegationProtocol) -> None:
        proto.submit(self._make_request())
        proto.accept("t-1", "worker-a")
        result = DelegationResult(
            task_id="t-1",
            status=DelegationStatus.COMPLETED,
            delegate="worker-a",
            response="Done!",
        )
        proto.complete(result)
        r = proto.get_result("t-1")
        assert r is not None
        assert r.status == DelegationStatus.COMPLETED
        assert r.response == "Done!"

    def test_get_pending(self, proto: DelegationProtocol) -> None:
        proto.submit(self._make_request("t-1"))
        proto.submit(self._make_request("t-2"))
        proto.accept("t-1", "worker-a")
        pending = proto.get_pending()
        assert len(pending) == 1
        assert pending[0].task_id == "t-2"

    def test_get_active(self, proto: DelegationProtocol) -> None:
        proto.submit(self._make_request("t-1"))
        proto.accept("t-1", "worker-a")
        active = proto.get_active()
        assert len(active) == 1
        req, delegate = active[0]
        assert req.task_id == "t-1"
        assert delegate == "worker-a"

    def test_completed_not_in_active(self, proto: DelegationProtocol) -> None:
        proto.submit(self._make_request("t-1"))
        proto.accept("t-1", "w")
        proto.complete(DelegationResult(task_id="t-1", status=DelegationStatus.COMPLETED, delegate="w"))
        assert proto.get_active() == []

    def test_cancel_sets_rejected(self, proto: DelegationProtocol) -> None:
        proto.submit(self._make_request())
        assert proto.cancel("t-1")
        r = proto.get_result("t-1")
        assert r is not None
        assert r.status == DelegationStatus.REJECTED

    def test_cancel_missing_returns_false(self, proto: DelegationProtocol) -> None:
        assert not proto.cancel("missing")

    def test_get_agent_delegations(self, proto: DelegationProtocol) -> None:
        proto.submit(self._make_request("t-1"))
        proto.submit(self._make_request("t-2"))
        proto.accept("t-1", "worker-a")
        proto.accept("t-2", "worker-b")
        delegations = proto.get_agent_delegations("worker-a")
        assert len(delegations) == 1
        assert delegations[0].task_id == "t-1"

    def test_clear(self, proto: DelegationProtocol) -> None:
        proto.submit(self._make_request())
        proto.accept("t-1", "w")
        proto.clear()
        assert proto.get_pending() == []
        assert proto.get_active() == []
        assert proto.get_request("t-1") is None

    def test_delegation_status_values(self) -> None:
        assert DelegationStatus.PENDING == "pending"
        assert DelegationStatus.ACCEPTED == "accepted"
        assert DelegationStatus.IN_PROGRESS == "in_progress"
        assert DelegationStatus.COMPLETED == "completed"
        assert DelegationStatus.FAILED == "failed"
        assert DelegationStatus.REJECTED == "rejected"


class TestTaskManager:
    @pytest.fixture()
    def tm(self) -> TaskManager:
        return TaskManager()

    def test_create_task_returns_id(self, tm: TaskManager) -> None:
        tid = tm.create_task("Do something")
        assert tid.startswith("task-")

    def test_create_increments_ids(self, tm: TaskManager) -> None:
        t1 = tm.create_task("A")
        t2 = tm.create_task("B")
        assert t1 != t2

    def test_get_task(self, tm: TaskManager) -> None:
        tid = tm.create_task("Foo")
        task = tm.get_task(tid)
        assert task is not None
        assert task.description == "Foo"
        assert task.status == TaskStatus.PENDING

    def test_get_task_missing(self, tm: TaskManager) -> None:
        assert tm.get_task("nope") is None

    def test_start_task(self, tm: TaskManager) -> None:
        tid = tm.create_task("Do it")
        assert tm.start_task(tid)
        task = tm.get_task(tid)
        assert task is not None
        assert task.status == TaskStatus.IN_PROGRESS

    def test_complete_task(self, tm: TaskManager) -> None:
        tid = tm.create_task("Do it")
        tm.start_task(tid)
        assert tm.complete_task(tid, result="Done")
        task = tm.get_task(tid)
        assert task is not None
        assert task.status == TaskStatus.COMPLETED
        assert task.result == "Done"

    def test_fail_task(self, tm: TaskManager) -> None:
        tid = tm.create_task("Do it")
        tm.start_task(tid)
        assert tm.fail_task(tid, error="oops")
        task = tm.get_task(tid)
        assert task is not None
        assert task.status == TaskStatus.FAILED

    def test_skip_task(self, tm: TaskManager) -> None:
        tid = tm.create_task("Do it")
        assert tm.skip_task(tid)
        task = tm.get_task(tid)
        assert task is not None
        assert task.status == TaskStatus.SKIPPED

    def test_blocked_by_dependency(self, tm: TaskManager) -> None:
        t1 = tm.create_task("First")
        t2 = tm.create_task("Second", dependencies=[t1])
        task2 = tm.get_task(t2)
        assert task2 is not None
        assert task2.status == TaskStatus.BLOCKED

    def test_start_blocked_fails(self, tm: TaskManager) -> None:
        t1 = tm.create_task("First")
        t2 = tm.create_task("Second", dependencies=[t1])
        assert not tm.start_task(t2)

    def test_completing_dep_unblocks(self, tm: TaskManager) -> None:
        t1 = tm.create_task("First")
        t2 = tm.create_task("Second", dependencies=[t1])
        tm.start_task(t1)
        tm.complete_task(t1)
        task2 = tm.get_task(t2)
        assert task2 is not None
        assert task2.status == TaskStatus.PENDING

    def test_skipping_dep_unblocks(self, tm: TaskManager) -> None:
        t1 = tm.create_task("First")
        t2 = tm.create_task("Second", dependencies=[t1])
        tm.skip_task(t1)
        task2 = tm.get_task(t2)
        assert task2 is not None
        assert task2.status == TaskStatus.PENDING

    def test_get_ready_tasks_only_unblocked(self, tm: TaskManager) -> None:
        t1 = tm.create_task("First")
        t2 = tm.create_task("Second", dependencies=[t1])
        t3 = tm.create_task("Third")
        ready = tm.get_ready_tasks()
        ready_ids = {t.id for t in ready}
        assert t1 in ready_ids
        assert t3 in ready_ids
        assert t2 not in ready_ids

    def test_progress_empty(self, tm: TaskManager) -> None:
        assert tm.progress == 1.0

    def test_progress_partial(self, tm: TaskManager) -> None:
        t1 = tm.create_task("A")
        t2 = tm.create_task("B")
        tm.start_task(t1)
        tm.complete_task(t1)
        assert tm.progress == pytest.approx(0.5)

    def test_is_complete(self, tm: TaskManager) -> None:
        t1 = tm.create_task("A")
        t2 = tm.create_task("B")
        assert not tm.is_complete
        tm.start_task(t1)
        tm.complete_task(t1)
        tm.skip_task(t2)
        assert tm.is_complete

    def test_total_tasks(self, tm: TaskManager) -> None:
        tm.create_task("A")
        tm.create_task("B")
        assert tm.total_tasks == 2

    def test_completed_count(self, tm: TaskManager) -> None:
        t1 = tm.create_task("A")
        tm.start_task(t1)
        tm.complete_task(t1)
        assert tm.completed_count == 1

    def test_pending_count(self, tm: TaskManager) -> None:
        c = tm.create_task("C")
        tm.create_task("A")
        t2 = tm.create_task("B", dependencies=[c])
        assert tm.pending_count == 3

    def test_in_progress_count(self, tm: TaskManager) -> None:
        t1 = tm.create_task("A")
        tm.start_task(t1)
        assert tm.in_progress_count == 1

    def test_failed_count(self, tm: TaskManager) -> None:
        t1 = tm.create_task("A")
        tm.start_task(t1)
        tm.fail_task(t1)
        assert tm.failed_count == 1

    def test_get_summary_no_tasks(self, tm: TaskManager) -> None:
        assert tm.get_summary() == "No tasks."

    def test_get_summary_with_tasks(self, tm: TaskManager) -> None:
        t1 = tm.create_task("A")
        tm.create_task("B")
        tm.start_task(t1)
        tm.complete_task(t1)
        summary = tm.get_summary()
        assert "1/2 complete" in summary

    def test_clear(self, tm: TaskManager) -> None:
        tm.create_task("A")
        tm.create_task("B")
        tm.clear()
        assert tm.total_tasks == 0

    def test_start_completed_task_fails(self, tm: TaskManager) -> None:
        t1 = tm.create_task("A")
        tm.start_task(t1)
        tm.complete_task(t1)
        assert not tm.start_task(t1)

    def test_start_missing_task_fails(self, tm: TaskManager) -> None:
        assert not tm.start_task("nope")

    def test_complete_missing_task_fails(self, tm: TaskManager) -> None:
        assert not tm.complete_task("nope")


class TestWorkLog:
    @pytest.fixture()
    def log(self) -> WorkLog:
        return WorkLog()

    def test_record_basic(self, log: WorkLog) -> None:
        log.record(WorkEntryType.ACTION, "Did something", tool="bash")
        assert log.entry_count == 1
        entries = log.entries
        assert entries[0].type == WorkEntryType.ACTION
        assert entries[0].description == "Did something"
        assert entries[0].tool == "bash"

    def test_action(self, log: WorkLog) -> None:
        log.action("Created file", tool="write_file", iteration=1)
        assert log.entries[0].type == WorkEntryType.ACTION

    def test_observation(self, log: WorkLog) -> None:
        log.observation("File has 50 lines", iteration=2)
        assert log.entries[0].type == WorkEntryType.OBSERVATION

    def test_decision(self, log: WorkLog) -> None:
        log.decision("Will refactor first")
        assert log.entries[0].type == WorkEntryType.DECISION

    def test_error(self, log: WorkLog) -> None:
        log.error("Syntax error on line 5")
        assert log.entries[0].type == WorkEntryType.ERROR

    def test_milestone(self, log: WorkLog) -> None:
        log.milestone("Tests passing")
        assert log.entries[0].type == WorkEntryType.MILESTONE

    def test_get_recent(self, log: WorkLog) -> None:
        for i in range(20):
            log.action(f"Action {i}")
        recent = log.get_recent(5)
        assert len(recent) == 5
        assert recent[0].description == "Action 15"
        assert recent[4].description == "Action 19"

    def test_get_recent_fewer_than_requested(self, log: WorkLog) -> None:
        log.action("Only one")
        recent = log.get_recent(10)
        assert len(recent) == 1

    def test_get_by_type(self, log: WorkLog) -> None:
        log.action("a1")
        log.error("e1")
        log.action("a2")
        log.error("e2")
        errors = log.get_by_type(WorkEntryType.ERROR)
        assert len(errors) == 2
        assert all(e.type == WorkEntryType.ERROR for e in errors)

    def test_get_summary_empty(self, log: WorkLog) -> None:
        assert log.get_summary() == "No work recorded."

    def test_get_summary_formats_entries(self, log: WorkLog) -> None:
        log.action("Did a thing", tool="bash")
        log.error("Oops")
        log.milestone("Checkpoint")
        summary = log.get_summary()
        assert "[bash]" in summary
        assert "!!" in summary
        assert "##" in summary

    def test_get_summary_prefixes(self, log: WorkLog) -> None:
        log.action("act")
        log.observation("obs")
        log.decision("dec")
        summary = log.get_summary()
        lines = summary.strip().splitlines()
        assert lines[0].startswith("->")
        assert lines[1].startswith("  ")
        assert lines[2].startswith("**")

    def test_max_entries_eviction(self) -> None:
        log = WorkLog(max_entries=5)
        for i in range(10):
            log.action(f"Action {i}")
        assert log.entry_count == 5
        assert log.entries[0].description == "Action 5"
        assert log.entries[4].description == "Action 9"

    def test_clear(self, log: WorkLog) -> None:
        log.action("a")
        log.error("e")
        log.clear()
        assert log.entry_count == 0
        assert log.entries == []


class TestClassifyComplexity:
    def test_simple_tasks(self) -> None:
        result = classify_complexity("fix typo in README")
        assert result.tier == ComplexityTier.SIMPLE

    def test_simple_question(self) -> None:
        result = classify_complexity("what is this function?")
        assert result.tier == ComplexityTier.SIMPLE

    def test_complex_task(self) -> None:
        result = classify_complexity(
            "Refactor the authentication module to use JWT, "
            "migrate the database schema, then integrate with "
            "the new security audit system"
        )
        assert result.tier in (ComplexityTier.MEDIUM, ComplexityTier.COMPLEX, ComplexityTier.DEEP_RESEARCH)

    def test_medium_task(self) -> None:
        result = classify_complexity("implement a new endpoint for user profiles")
        assert result.tier in (ComplexityTier.SIMPLE, ComplexityTier.MEDIUM, ComplexityTier.COMPLEX)

    def test_assessment_has_signals(self) -> None:
        result = classify_complexity("build a REST API")
        assert len(result.signals) > 0
        assert result.confidence > 0.0
        assert result.reasoning

    def test_confidence_range(self) -> None:
        result = classify_complexity("explain how the config works")
        assert 0.0 < result.confidence <= 1.0


class TestDecomposeSimple:
    def test_simple_task_single_subtask(self) -> None:
        result = decompose_simple("fix typo in README")
        assert result.strategy == "single_task"
        assert len(result.subtasks) == 1
        assert result.subtasks[0].description == "fix typo in README"

    def test_sequential_split(self) -> None:
        result = decompose_simple(
            "First create the database schema. Then implement the API endpoints. "
            "Finally write the tests."
        )
        assert len(result.subtasks) >= 2
        if len(result.subtasks) > 1:
            assert result.subtasks[1].dependencies == [0]

    def test_numbered_steps(self) -> None:
        result = decompose_simple(
            "Refactor the codebase: 1) Create models for the auth module. "
            "2) Add API routes for user management. "
            "3) Write integration tests for everything."
        )
        assert len(result.subtasks) >= 2


class TestSkillLoader:
    def test_load_from_directory(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / ".attocode" / "skills" / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# My Skill\n\nDo awesome things.")
        loader = SkillLoader(project_root=tmp_path)
        loader.load()
        assert loader.has("my-skill")
        skill = loader.get("my-skill")
        assert skill is not None
        assert skill.description == "My Skill"
        assert "awesome things" in skill.content

    def test_get_missing_skill(self, tmp_path: Path) -> None:
        loader = SkillLoader(project_root=tmp_path)
        loader.load()
        assert loader.get("nonexistent") is None

    def test_has(self, tmp_path: Path) -> None:
        loader = SkillLoader(project_root=tmp_path)
        loader.load()
        assert not loader.has("nope")

    def test_list_skills(self, tmp_path: Path) -> None:
        for name in ("alpha", "beta"):
            d = tmp_path / ".attocode" / "skills" / name
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text(f"# {name}\n\nContent for {name}.")
        loader = SkillLoader(project_root=tmp_path)
        loader.load()
        skills = loader.list_skills()
        names = {s.name for s in skills}
        assert names == {"alpha", "beta"}

    def test_auto_load_on_get(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / ".attocode" / "skills" / "auto"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# Auto\n\nAuto-loaded.")
        loader = SkillLoader(project_root=tmp_path)
        skill = loader.get("auto")
        assert skill is not None

    def test_skill_source_is_project(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / ".attocode" / "skills" / "proj"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# Proj\n\nProject skill.")
        loader = SkillLoader(project_root=tmp_path)
        loader.load()
        assert loader.get("proj") is not None
        assert loader.get("proj").source == "project"

    def test_skill_path_recorded(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / ".attocode" / "skills" / "pathcheck"
        skill_dir.mkdir(parents=True)
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text("# PathCheck\n\nSome content.")
        loader = SkillLoader(project_root=tmp_path)
        loader.load()
        skill = loader.get("pathcheck")
        assert skill is not None
        assert skill.path == str(skill_file)

    def test_reload(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / ".attocode" / "skills" / "reload-me"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# V1\n\nVersion 1.")
        loader = SkillLoader(project_root=tmp_path)
        loader.load()
        assert loader.get("reload-me").description == "V1"
        (skill_dir / "SKILL.md").write_text("# V2\n\nVersion 2.")
        loader.reload()
        assert loader.get("reload-me").description == "V2"

    def test_directory_without_skill_md_ignored(self, tmp_path: Path) -> None:
        d = tmp_path / ".attocode" / "skills" / "empty"
        d.mkdir(parents=True)
        loader = SkillLoader(project_root=tmp_path)
        loader.load()
        assert not loader.has("empty")


class TestParseSkillContent:
    def test_heading_description(self) -> None:
        desc, body, meta = _parse_skill_content("# My Skill\n\nBody text here.")
        assert desc == "My Skill"
        assert body == "Body text here."

    def test_frontmatter_description(self) -> None:
        content = "---\ndescription: A cool skill\n---\n\nBody content."
        desc, body, meta = _parse_skill_content(content)
        assert desc == "A cool skill"
        assert body == "Body content."

    def test_frontmatter_quoted_description(self) -> None:
        content = '---\ndescription: "Quoted desc"\n---\n\nStuff.'
        desc, body, meta = _parse_skill_content(content)
        assert desc == "Quoted desc"

    def test_empty_content(self) -> None:
        desc, body, meta = _parse_skill_content("")
        assert desc == ""
        assert body == ""

    def test_body_only(self) -> None:
        desc, body, meta = _parse_skill_content("Just plain text.")
        assert desc == ""
        assert body == "Just plain text."

    def test_frontmatter_with_metadata(self) -> None:
        content = "---\ndescription: A skill\nversion: 2.0\ndepends_on: base, helper\nlifecycle: long_running\n---\n\nContent."
        desc, body, meta = _parse_skill_content(content)
        assert desc == "A skill"
        assert meta["version"] == "2.0"
        assert meta["depends_on"] == ["base", "helper"]
        assert meta["lifecycle"] == "long_running"


class TestSkillExecutor:
    @pytest.fixture()
    def loader_with_skill(self, tmp_path: Path) -> SkillLoader:
        skill_dir = tmp_path / ".attocode" / "skills" / "greet"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# Greet\n\nSay hello to everyone.")
        loader = SkillLoader(project_root=tmp_path)
        loader.load()
        return loader

    def test_execute_found_skill(self, loader_with_skill: SkillLoader) -> None:
        executor = SkillExecutor(loader_with_skill)
        result = executor.execute("greet")
        assert result.success
        assert "Say hello to everyone" in result.output
        assert result.skill_name == "greet"

    def test_execute_with_args(self, loader_with_skill: SkillLoader) -> None:
        executor = SkillExecutor(loader_with_skill)
        result = executor.execute("greet", args="name=World")
        assert result.success
        assert "Arguments: name=World" in result.output

    def test_execute_missing_skill(self, loader_with_skill: SkillLoader) -> None:
        executor = SkillExecutor(loader_with_skill)
        result = executor.execute("nonexistent")
        assert not result.success
        assert result.error is not None
        assert "not found" in result.error

    def test_execute_empty_skill(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / ".attocode" / "skills" / "empty"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# Empty\n")
        loader = SkillLoader(project_root=tmp_path)
        loader.load()
        executor = SkillExecutor(loader)
        result = executor.execute("empty")
        assert not result.success
        assert "no content" in result.error

    def test_list_available(self, loader_with_skill: SkillLoader) -> None:
        executor = SkillExecutor(loader_with_skill)
        available = executor.list_available()
        assert len(available) >= 1
        names = {a["name"] for a in available}
        assert "greet" in names
        entry = next(a for a in available if a["name"] == "greet")
        assert "description" in entry
        assert "source" in entry


class TestMCPDataclasses:
    def test_mcp_tool_creation(self) -> None:
        tool = MCPTool(
            name="search",
            description="Search the web",
            input_schema={"type": "object", "properties": {"q": {"type": "string"}}},
            server_name="web-server",
        )
        assert tool.name == "search"
        assert tool.description == "Search the web"
        assert tool.server_name == "web-server"
        assert "properties" in tool.input_schema

    def test_mcp_tool_defaults(self) -> None:
        tool = MCPTool(name="ping", description="Ping")
        assert tool.input_schema == {}
        assert tool.server_name == ""

    def test_mcp_call_result_success(self) -> None:
        r = MCPCallResult(success=True, result="42")
        assert r.success
        assert r.result == "42"
        assert r.error is None

    def test_mcp_call_result_failure(self) -> None:
        r = MCPCallResult(success=False, error="timeout")
        assert not r.success
        assert r.error == "timeout"

    def test_mcp_call_result_defaults(self) -> None:
        r = MCPCallResult(success=True)
        assert r.result is None
        assert r.error is None


class TestMCPClient:
    def test_client_properties_defaults(self) -> None:
        client = MCPClient(
            server_command="node",
            server_args=["server.js"],
            server_name="test-server",
        )
        assert not client.is_connected
        assert client.server_name == "test-server"
        assert client.tools == []

    def test_client_default_args(self) -> None:
        client = MCPClient(server_command="python")
        assert client.server_name == ""
        assert not client.is_connected
