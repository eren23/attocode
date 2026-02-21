"""Tests for swarm types, helpers, and config_loader modules.

Covers:
- All StrEnum types and their values
- Dataclass instantiation and defaults for every swarm type
- SwarmConfig defaults and DEFAULT_SWARM_CONFIG
- BUILTIN_TASK_TYPE_CONFIGS completeness
- FAILURE_MODE_THRESHOLDS values
- swarm_event() factory
- FixupTask inheritance
- is_hollow_completion detection heuristics
- has_future_intent_language detection
- repo_looks_unscaffolded filesystem checks
- parse_swarm_yaml parsing
- load_swarm_yaml_config search order
- yaml_to_swarm_config mapping
- merge_swarm_configs three-way merge
- normalize_capabilities alias mapping
- normalize_swarm_model_config validation
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, fields
from typing import Any

import pytest

from attocode.integrations.swarm.config_loader import (
    _guess_provider_prefix,
    _to_snake,
    merge_swarm_configs,
    normalize_capabilities,
    normalize_swarm_model_config,
    parse_swarm_yaml,
    load_swarm_yaml_config,
    yaml_to_swarm_config,
)
from attocode.integrations.swarm.helpers import (
    BOILERPLATE_INDICATORS,
    FAILURE_INDICATORS,
    has_future_intent_language,
    is_hollow_completion,
    repo_looks_unscaffolded,
)
from attocode.integrations.swarm.types import (
    BUILTIN_TASK_TYPE_CONFIGS,
    DEFAULT_SWARM_CONFIG,
    FAILURE_MODE_THRESHOLDS,
    AcceptanceCriterion,
    ArtifactFile,
    ArtifactInventory,
    AutoSplitConfig,
    CompletionGuardConfig,
    DependencyGraph,
    FileConflictStrategy,
    FixupTask,
    HierarchyConfig,
    HierarchyRoleConfig,
    IntegrationTestPlan,
    IntegrationTestStep,
    ModelHealthRecord,
    ModelValidationConfig,
    OrchestratorDecision,
    PartialContext,
    ProbeFailureStrategy,
    ResourceConflict,
    RetryContext,
    SmartDecompositionResult,
    SmartSubtask,
    SpawnResult,
    SubtaskType,
    SwarmBudgetStatus,
    SwarmCheckpoint,
    SwarmConfig,
    SwarmError,
    SwarmEvent,
    SwarmExecutionResult,
    SwarmExecutionStats,
    SwarmOrchestratorStatus,
    SwarmPhase,
    SwarmPlan,
    SwarmQueueStats,
    SwarmStatus,
    SwarmTask,
    SwarmTaskResult,
    SwarmTaskStatus,
    SwarmWorkerSpec,
    SynthesisResult,
    TaskCheckpointState,
    TaskFailureMode,
    TaskTypeConfig,
    VerificationResult,
    VerificationStepResult,
    WaveReviewResult,
    WorkerCapability,
    WorkerRole,
    swarm_event,
)


# ============================================================================
# StrEnum Tests
# ============================================================================


class TestSwarmTaskStatus:
    def test_all_values(self) -> None:
        expected = {
            "pending", "ready", "dispatched",
            "completed", "failed", "skipped", "decomposed",
        }
        actual = {s.value for s in SwarmTaskStatus}
        assert actual == expected

    def test_member_count(self) -> None:
        assert len(SwarmTaskStatus) == 7

    def test_string_equality(self) -> None:
        assert SwarmTaskStatus.PENDING == "pending"
        assert SwarmTaskStatus.COMPLETED == "completed"

    def test_from_value(self) -> None:
        assert SwarmTaskStatus("pending") is SwarmTaskStatus.PENDING
        assert SwarmTaskStatus("failed") is SwarmTaskStatus.FAILED

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError):
            SwarmTaskStatus("nonexistent")


class TestTaskFailureMode:
    def test_all_values(self) -> None:
        expected = {"timeout", "rate-limit", "error", "quality", "hollow", "cascade", "recoverable", "terminal"}
        actual = {m.value for m in TaskFailureMode}
        assert actual == expected

    def test_member_count(self) -> None:
        assert len(TaskFailureMode) == 8

    def test_string_equality(self) -> None:
        assert TaskFailureMode.TIMEOUT == "timeout"
        assert TaskFailureMode.RATE_LIMIT == "rate-limit"
        assert TaskFailureMode.HOLLOW == "hollow"

    def test_from_value(self) -> None:
        assert TaskFailureMode("cascade") is TaskFailureMode.CASCADE


class TestWorkerCapability:
    def test_all_values(self) -> None:
        expected = {"code", "research", "review", "test", "document", "write"}
        actual = {c.value for c in WorkerCapability}
        assert actual == expected

    def test_member_count(self) -> None:
        assert len(WorkerCapability) == 6

    def test_string_equality(self) -> None:
        assert WorkerCapability.CODE == "code"
        assert WorkerCapability.RESEARCH == "research"


class TestWorkerRole:
    def test_all_values(self) -> None:
        expected = {"executor", "manager", "judge"}
        actual = {r.value for r in WorkerRole}
        assert actual == expected

    def test_member_count(self) -> None:
        assert len(WorkerRole) == 3

    def test_string_equality(self) -> None:
        assert WorkerRole.EXECUTOR == "executor"
        assert WorkerRole.JUDGE == "judge"


class TestSubtaskType:
    def test_all_values(self) -> None:
        expected = {
            "research", "analysis", "design", "implement", "test",
            "refactor", "review", "document", "integrate", "deploy", "merge",
        }
        actual = {t.value for t in SubtaskType}
        assert actual == expected

    def test_member_count(self) -> None:
        assert len(SubtaskType) == 11

    def test_string_equality(self) -> None:
        assert SubtaskType.IMPLEMENT == "implement"
        assert SubtaskType.MERGE == "merge"


class TestSwarmPhase:
    def test_all_values(self) -> None:
        expected = {
            "idle", "decomposing", "scheduling", "planning",
            "executing", "verifying", "synthesizing",
            "completed", "failed",
        }
        actual = {p.value for p in SwarmPhase}
        assert actual == expected

    def test_member_count(self) -> None:
        assert len(SwarmPhase) == 9


class TestFileConflictStrategy:
    def test_all_values(self) -> None:
        expected = {"claim-based", "serialize"}
        actual = {s.value for s in FileConflictStrategy}
        assert actual == expected

    def test_member_count(self) -> None:
        assert len(FileConflictStrategy) == 2


class TestProbeFailureStrategy:
    def test_all_values(self) -> None:
        expected = {"abort", "warn-and-try"}
        actual = {s.value for s in ProbeFailureStrategy}
        assert actual == expected

    def test_member_count(self) -> None:
        assert len(ProbeFailureStrategy) == 2


# ============================================================================
# TaskTypeConfig and BUILTIN_TASK_TYPE_CONFIGS
# ============================================================================


class TestTaskTypeConfig:
    def test_instantiation(self) -> None:
        cfg = TaskTypeConfig(
            capability=WorkerCapability.CODE,
            requires_tool_calls=True,
            prompt_template="code",
            timeout=300,
        )
        assert cfg.capability == WorkerCapability.CODE
        assert cfg.requires_tool_calls is True
        assert cfg.prompt_template == "code"
        assert cfg.timeout == 300
        assert cfg.min_tokens == 20_000
        assert cfg.max_tokens == 80_000

    def test_custom_token_bounds(self) -> None:
        cfg = TaskTypeConfig(
            capability=WorkerCapability.TEST,
            requires_tool_calls=False,
            prompt_template="research",
            timeout=120,
            min_tokens=5_000,
            max_tokens=10_000,
        )
        assert cfg.min_tokens == 5_000
        assert cfg.max_tokens == 10_000


class TestBuiltinTaskTypeConfigs:
    def test_all_subtask_types_present(self) -> None:
        for st in SubtaskType:
            assert st.value in BUILTIN_TASK_TYPE_CONFIGS, f"Missing config for {st.value}"

    def test_expected_count(self) -> None:
        assert len(BUILTIN_TASK_TYPE_CONFIGS) == 11

    def test_implement_config(self) -> None:
        cfg = BUILTIN_TASK_TYPE_CONFIGS["implement"]
        assert cfg.capability == WorkerCapability.CODE
        assert cfg.requires_tool_calls is True
        assert cfg.prompt_template == "code"
        assert cfg.timeout == 300
        assert cfg.min_tokens == 40_000
        assert cfg.max_tokens == 150_000

    def test_research_config(self) -> None:
        cfg = BUILTIN_TASK_TYPE_CONFIGS["research"]
        assert cfg.capability == WorkerCapability.RESEARCH
        assert cfg.requires_tool_calls is False
        assert cfg.prompt_template == "research"

    def test_test_config(self) -> None:
        cfg = BUILTIN_TASK_TYPE_CONFIGS["test"]
        assert cfg.capability == WorkerCapability.TEST
        assert cfg.requires_tool_calls is True

    def test_review_config(self) -> None:
        cfg = BUILTIN_TASK_TYPE_CONFIGS["review"]
        assert cfg.capability == WorkerCapability.REVIEW
        assert cfg.requires_tool_calls is False

    def test_document_config(self) -> None:
        cfg = BUILTIN_TASK_TYPE_CONFIGS["document"]
        assert cfg.capability == WorkerCapability.DOCUMENT
        assert cfg.requires_tool_calls is True
        assert cfg.prompt_template == "document"

    def test_merge_config(self) -> None:
        cfg = BUILTIN_TASK_TYPE_CONFIGS["merge"]
        assert cfg.capability == WorkerCapability.WRITE
        assert cfg.requires_tool_calls is False
        assert cfg.prompt_template == "synthesis"

    def test_refactor_config(self) -> None:
        cfg = BUILTIN_TASK_TYPE_CONFIGS["refactor"]
        assert cfg.capability == WorkerCapability.CODE
        assert cfg.requires_tool_calls is True

    def test_integrate_config(self) -> None:
        cfg = BUILTIN_TASK_TYPE_CONFIGS["integrate"]
        assert cfg.capability == WorkerCapability.CODE
        assert cfg.requires_tool_calls is True

    def test_deploy_config(self) -> None:
        cfg = BUILTIN_TASK_TYPE_CONFIGS["deploy"]
        assert cfg.capability == WorkerCapability.CODE

    def test_analysis_config(self) -> None:
        cfg = BUILTIN_TASK_TYPE_CONFIGS["analysis"]
        assert cfg.capability == WorkerCapability.RESEARCH

    def test_design_config(self) -> None:
        cfg = BUILTIN_TASK_TYPE_CONFIGS["design"]
        assert cfg.capability == WorkerCapability.RESEARCH


# ============================================================================
# FAILURE_MODE_THRESHOLDS
# ============================================================================


class TestFailureModeThresholds:
    def test_keys_match_enum(self) -> None:
        for fm in TaskFailureMode:
            assert fm.value in FAILURE_MODE_THRESHOLDS

    def test_count(self) -> None:
        assert len(FAILURE_MODE_THRESHOLDS) == 8

    def test_timeout_value(self) -> None:
        assert FAILURE_MODE_THRESHOLDS["timeout"] == 0.3

    def test_rate_limit_value(self) -> None:
        assert FAILURE_MODE_THRESHOLDS["rate-limit"] == 0.3

    def test_error_value(self) -> None:
        assert FAILURE_MODE_THRESHOLDS["error"] == 0.5

    def test_quality_value(self) -> None:
        assert FAILURE_MODE_THRESHOLDS["quality"] == 0.7

    def test_hollow_value(self) -> None:
        assert FAILURE_MODE_THRESHOLDS["hollow"] == 0.7

    def test_cascade_value(self) -> None:
        assert FAILURE_MODE_THRESHOLDS["cascade"] == 0.8

    def test_all_values_between_0_and_1(self) -> None:
        for v in FAILURE_MODE_THRESHOLDS.values():
            assert 0.0 < v <= 1.0


# ============================================================================
# Dataclass Instantiation Tests
# ============================================================================


class TestSwarmWorkerSpec:
    def test_defaults(self) -> None:
        w = SwarmWorkerSpec(name="w1", model="anthropic/claude-sonnet")
        assert w.name == "w1"
        assert w.model == "anthropic/claude-sonnet"
        assert w.capabilities == [WorkerCapability.CODE]
        assert w.context_window == 128_000
        assert w.persona == ""
        assert w.role == WorkerRole.EXECUTOR
        assert w.max_tokens == 50_000
        assert w.policy_profile == ""
        assert w.allowed_tools is None
        assert w.denied_tools is None
        assert w.extra_tools is None
        assert w.prompt_tier == "full"

    def test_custom_values(self) -> None:
        w = SwarmWorkerSpec(
            name="reviewer",
            model="openai/gpt-4o",
            capabilities=[WorkerCapability.REVIEW, WorkerCapability.RESEARCH],
            role=WorkerRole.JUDGE,
            max_tokens=30_000,
            prompt_tier="reduced",
        )
        assert w.role == WorkerRole.JUDGE
        assert len(w.capabilities) == 2
        assert w.prompt_tier == "reduced"


class TestAutoSplitConfig:
    def test_defaults(self) -> None:
        a = AutoSplitConfig()
        assert a.enabled is True
        assert a.complexity_floor == 6
        assert a.splittable_types == ["implement", "refactor", "test"]
        assert a.max_subtasks == 4


class TestCompletionGuardConfig:
    def test_defaults(self) -> None:
        c = CompletionGuardConfig()
        assert c.require_concrete_artifacts_for_action_tasks is True
        assert c.reject_future_intent_outputs is True


class TestModelValidationConfig:
    def test_defaults(self) -> None:
        m = ModelValidationConfig()
        assert m.mode == "autocorrect"
        assert m.on_invalid == "warn"


class TestHierarchyConfig:
    def test_defaults(self) -> None:
        h = HierarchyConfig()
        assert isinstance(h.manager, HierarchyRoleConfig)
        assert isinstance(h.judge, HierarchyRoleConfig)
        assert h.manager.model is None
        assert h.judge.model is None

    def test_with_models(self) -> None:
        h = HierarchyConfig(
            manager=HierarchyRoleConfig(model="anthropic/claude-opus"),
            judge=HierarchyRoleConfig(model="openai/gpt-4o"),
        )
        assert h.manager.model == "anthropic/claude-opus"
        assert h.judge.model == "openai/gpt-4o"


class TestRetryContext:
    def test_defaults(self) -> None:
        r = RetryContext()
        assert r.previous_feedback == ""
        assert r.previous_score == 0
        assert r.attempt == 0
        assert r.previous_model is None
        assert r.previous_files is None
        assert r.swarm_progress is None

    def test_custom(self) -> None:
        r = RetryContext(
            previous_feedback="output was incomplete",
            previous_score=2,
            attempt=1,
            previous_model="openai/gpt-4o",
        )
        assert r.attempt == 1
        assert r.previous_score == 2


class TestPartialContext:
    def test_defaults(self) -> None:
        p = PartialContext()
        assert p.succeeded == []
        assert p.failed == []
        assert p.ratio == 0.0

    def test_custom(self) -> None:
        p = PartialContext(
            succeeded=["task A completed"],
            failed=["task B failed"],
            ratio=0.5,
        )
        assert len(p.succeeded) == 1
        assert p.ratio == 0.5


class TestSwarmTaskResult:
    def test_minimal(self) -> None:
        r = SwarmTaskResult(success=True, output="Done")
        assert r.success is True
        assert r.output == "Done"
        assert r.quality_score is None
        assert r.tokens_used == 0
        assert r.cost_used == 0.0
        assert r.duration_ms == 0
        assert r.files_modified is None
        assert r.tool_calls is None
        assert r.model == ""
        assert r.degraded is False

    def test_full(self) -> None:
        r = SwarmTaskResult(
            success=False,
            output="Error occurred",
            quality_score=2,
            quality_feedback="Low quality",
            tokens_used=15_000,
            cost_used=0.02,
            duration_ms=5000,
            files_modified=["a.py"],
            tool_calls=3,
            model="anthropic/claude-sonnet",
            degraded=True,
        )
        assert r.quality_score == 2
        assert r.degraded is True
        assert r.files_modified == ["a.py"]


class TestSwarmTask:
    def test_minimal(self) -> None:
        t = SwarmTask(id="t1", description="Implement feature X")
        assert t.id == "t1"
        assert t.description == "Implement feature X"
        assert t.type == SubtaskType.IMPLEMENT
        assert t.dependencies == []
        assert t.status == SwarmTaskStatus.PENDING
        assert t.complexity == 5
        assert t.wave == 0
        assert t.target_files is None
        assert t.result is None
        assert t.attempts == 0
        assert t.is_foundation is False

    def test_with_dependencies(self) -> None:
        t = SwarmTask(
            id="t2",
            description="Write tests",
            type=SubtaskType.TEST,
            dependencies=["t1"],
            complexity=3,
            wave=1,
        )
        assert t.dependencies == ["t1"]
        assert t.type == SubtaskType.TEST
        assert t.wave == 1

    def test_with_result(self) -> None:
        result = SwarmTaskResult(success=True, output="Done", tool_calls=5)
        t = SwarmTask(
            id="t3",
            description="Review code",
            result=result,
            status=SwarmTaskStatus.COMPLETED,
        )
        assert t.result is not None
        assert t.result.success is True
        assert t.result.tool_calls == 5


class TestFixupTask:
    def test_inherits_swarm_task(self) -> None:
        assert issubclass(FixupTask, SwarmTask)

    def test_defaults(self) -> None:
        f = FixupTask(id="fix1", description="Fix lint errors")
        assert f.fixes_task_id == ""
        assert f.fix_instructions == ""
        assert f.id == "fix1"
        assert f.status == SwarmTaskStatus.PENDING

    def test_custom(self) -> None:
        f = FixupTask(
            id="fix2",
            description="Fix failing test",
            fixes_task_id="t5",
            fix_instructions="Update assertion on line 42",
            type=SubtaskType.TEST,
        )
        assert f.fixes_task_id == "t5"
        assert f.fix_instructions == "Update assertion on line 42"
        assert f.type == SubtaskType.TEST


class TestSwarmPlan:
    def test_defaults(self) -> None:
        p = SwarmPlan()
        assert p.acceptance_criteria == []
        assert p.integration_test_plan is None
        assert p.reasoning == ""

    def test_with_criteria(self) -> None:
        crit = AcceptanceCriterion(task_id="t1", criteria=["File exists", "Tests pass"])
        plan = SwarmPlan(
            acceptance_criteria=[crit],
            reasoning="Because we need it",
        )
        assert len(plan.acceptance_criteria) == 1
        assert plan.acceptance_criteria[0].criteria == ["File exists", "Tests pass"]


class TestAcceptanceCriterion:
    def test_defaults(self) -> None:
        ac = AcceptanceCriterion(task_id="t1")
        assert ac.task_id == "t1"
        assert ac.criteria == []


class TestIntegrationTestStep:
    def test_defaults(self) -> None:
        s = IntegrationTestStep(description="Run npm test")
        assert s.description == "Run npm test"
        assert s.command == ""
        assert s.expected_result == ""
        assert s.required is True


class TestIntegrationTestPlan:
    def test_defaults(self) -> None:
        p = IntegrationTestPlan()
        assert p.description == ""
        assert p.steps == []
        assert p.success_criteria == ""


class TestVerificationStepResult:
    def test_instantiation(self) -> None:
        v = VerificationStepResult(step_index=0, description="Check file", passed=True)
        assert v.step_index == 0
        assert v.passed is True
        assert v.output == ""


class TestVerificationResult:
    def test_defaults(self) -> None:
        v = VerificationResult(passed=True)
        assert v.passed is True
        assert v.steps == []
        assert v.summary == ""


class TestArtifactFile:
    def test_defaults(self) -> None:
        af = ArtifactFile(path="src/main.py")
        assert af.path == "src/main.py"
        assert af.size_bytes == 0
        assert af.exists is True


class TestArtifactInventory:
    def test_defaults(self) -> None:
        ai = ArtifactInventory()
        assert ai.files == []
        assert ai.total_files == 0
        assert ai.total_bytes == 0


class TestSwarmExecutionStats:
    def test_defaults(self) -> None:
        s = SwarmExecutionStats()
        assert s.total_tasks == 0
        assert s.completed_tasks == 0
        assert s.failed_tasks == 0
        assert s.skipped_tasks == 0
        assert s.total_tokens == 0
        assert s.total_cost == 0.0
        assert s.total_duration_ms == 0
        assert s.quality_rejections == 0
        assert s.retries == 0
        assert s.waves_completed == 0
        assert s.orchestrator_tokens == 0
        assert s.orchestrator_cost == 0.0


class TestSwarmExecutionResult:
    def test_minimal(self) -> None:
        r = SwarmExecutionResult(success=True, summary="All done")
        assert r.success is True
        assert r.summary == "All done"
        assert isinstance(r.stats, SwarmExecutionStats)
        assert r.errors == []
        assert r.plan is None
        assert r.verification is None
        assert r.artifact_inventory is None
        assert r.task_results == {}


class TestModelHealthRecord:
    def test_defaults(self) -> None:
        m = ModelHealthRecord(model="anthropic/claude-sonnet")
        assert m.model == "anthropic/claude-sonnet"
        assert m.successes == 0
        assert m.failures == 0
        assert m.rate_limits == 0
        assert m.last_rate_limit is None
        assert m.average_latency_ms == 0.0
        assert m.healthy is True
        assert m.quality_rejections == 0
        assert m.success_rate == 1.0


class TestOrchestratorDecision:
    def test_instantiation(self) -> None:
        d = OrchestratorDecision(
            timestamp=1234.0,
            phase="executing",
            decision="retry-task",
            reasoning="Quality too low",
        )
        assert d.timestamp == 1234.0
        assert d.phase == "executing"


class TestSwarmError:
    def test_defaults(self) -> None:
        e = SwarmError(timestamp=999.0, phase="planning", message="oops")
        assert e.task_id is None

    def test_with_task_id(self) -> None:
        e = SwarmError(timestamp=999.0, phase="executing", message="fail", task_id="t1")
        assert e.task_id == "t1"


class TestTaskCheckpointState:
    def test_defaults(self) -> None:
        s = TaskCheckpointState(id="t1", status="completed")
        assert s.id == "t1"
        assert s.status == "completed"
        assert s.result is None
        assert s.attempts == 0
        assert s.wave == 0
        assert s.complexity == 5
        assert s.dependencies == []
        assert s.is_foundation is False


class TestSwarmCheckpoint:
    def test_defaults(self) -> None:
        cp = SwarmCheckpoint(session_id="s1", timestamp=100.0, phase="executing")
        assert cp.session_id == "s1"
        assert cp.timestamp == 100.0
        assert cp.phase == "executing"
        assert cp.plan is None
        assert cp.task_states == []
        assert cp.waves == []
        assert cp.current_wave == 0
        assert cp.stats == {}
        assert cp.model_health == []
        assert cp.decisions == []
        assert cp.errors == []
        assert cp.original_prompt == ""
        assert cp.shared_context is None
        assert cp.shared_economics is None


class TestSwarmQueueStats:
    def test_defaults(self) -> None:
        q = SwarmQueueStats()
        assert q.ready == 0
        assert q.running == 0
        assert q.completed == 0
        assert q.failed == 0
        assert q.skipped == 0
        assert q.total == 0


class TestSwarmBudgetStatus:
    def test_defaults(self) -> None:
        b = SwarmBudgetStatus()
        assert b.tokens_used == 0
        assert b.tokens_total == 0
        assert b.cost_used == 0.0
        assert b.cost_total == 0.0


class TestSwarmOrchestratorStatus:
    def test_defaults(self) -> None:
        o = SwarmOrchestratorStatus()
        assert o.tokens == 0
        assert o.cost == 0.0
        assert o.calls == 0


class TestSwarmStatus:
    def test_defaults(self) -> None:
        s = SwarmStatus()
        assert s.phase == SwarmPhase.IDLE
        assert s.current_wave == 0
        assert s.total_waves == 0
        assert s.active_workers == []
        assert isinstance(s.queue, SwarmQueueStats)
        assert isinstance(s.budget, SwarmBudgetStatus)
        assert isinstance(s.orchestrator, SwarmOrchestratorStatus)


class TestSpawnResult:
    def test_defaults(self) -> None:
        r = SpawnResult(success=True)
        assert r.output == ""
        assert r.tool_calls == 0
        assert r.files_modified is None
        assert r.closure_report is None
        assert r.metrics is None

    def test_custom(self) -> None:
        r = SpawnResult(
            success=False,
            output="Error",
            tool_calls=5,
            files_modified=["a.py"],
        )
        assert r.tool_calls == 5


class TestWaveReviewResult:
    def test_defaults(self) -> None:
        w = WaveReviewResult(assessment="good")
        assert w.assessment == "good"
        assert w.task_assessments == []
        assert w.fixup_instructions == []


class TestSynthesisResult:
    def test_defaults(self) -> None:
        s = SynthesisResult()
        assert s.summary == ""
        assert s.findings == []
        assert s.recommendations == []


class TestResourceConflict:
    def test_defaults(self) -> None:
        rc = ResourceConflict(file_path="src/main.py")
        assert rc.file_path == "src/main.py"
        assert rc.task_ids == []
        assert rc.conflict_type == "write-write"


class TestSmartSubtask:
    def test_defaults(self) -> None:
        s = SmartSubtask(id="sub1", description="Do X")
        assert s.type == "implement"
        assert s.complexity == 5
        assert s.dependencies == []
        assert s.target_files is None


class TestDependencyGraph:
    def test_defaults(self) -> None:
        dg = DependencyGraph()
        assert dg.parallel_groups == []
        assert dg.conflicts == []


class TestSmartDecompositionResult:
    def test_defaults(self) -> None:
        d = SmartDecompositionResult()
        assert d.subtasks == []
        assert d.strategy == ""
        assert d.reasoning == ""
        assert isinstance(d.dependency_graph, DependencyGraph)
        assert d.llm_assisted is True


# ============================================================================
# SwarmEvent Tests
# ============================================================================


class TestSwarmEvent:
    def test_instantiation(self) -> None:
        e = SwarmEvent(type="task.completed", data={"task_id": "t1"})
        assert e.type == "task.completed"
        assert e.data == {"task_id": "t1"}

    def test_default_data(self) -> None:
        e = SwarmEvent(type="swarm.started")
        assert e.data == {}


class TestSwarmEventFactory:
    def test_basic(self) -> None:
        e = swarm_event("task.started", task_id="t1", wave=0)
        assert e.type == "task.started"
        assert e.data["task_id"] == "t1"
        assert e.data["wave"] == 0

    def test_no_kwargs(self) -> None:
        e = swarm_event("swarm.idle")
        assert e.type == "swarm.idle"
        assert e.data == {}

    def test_returns_swarm_event_type(self) -> None:
        e = swarm_event("test")
        assert isinstance(e, SwarmEvent)


# ============================================================================
# SwarmConfig Defaults Tests
# ============================================================================


class TestSwarmConfig:
    def test_default_config_exists(self) -> None:
        assert DEFAULT_SWARM_CONFIG is not None
        assert isinstance(DEFAULT_SWARM_CONFIG, SwarmConfig)

    def test_enabled_default(self) -> None:
        assert DEFAULT_SWARM_CONFIG.enabled is True

    def test_orchestrator_model_default(self) -> None:
        assert DEFAULT_SWARM_CONFIG.orchestrator_model == ""

    def test_workers_default_empty(self) -> None:
        assert DEFAULT_SWARM_CONFIG.workers == []

    def test_concurrency_defaults(self) -> None:
        assert DEFAULT_SWARM_CONFIG.max_concurrency == 3
        assert DEFAULT_SWARM_CONFIG.total_budget == 5_000_000
        assert DEFAULT_SWARM_CONFIG.max_cost == 10.0
        assert DEFAULT_SWARM_CONFIG.orchestrator_reserve_ratio == 0.15
        assert DEFAULT_SWARM_CONFIG.max_tokens_per_worker == 50_000
        assert DEFAULT_SWARM_CONFIG.worker_timeout == 120_000
        assert DEFAULT_SWARM_CONFIG.worker_max_iterations == 15

    def test_quality_defaults(self) -> None:
        assert DEFAULT_SWARM_CONFIG.quality_gates is True
        assert DEFAULT_SWARM_CONFIG.quality_threshold == 3
        assert DEFAULT_SWARM_CONFIG.quality_gate_model == ""
        assert DEFAULT_SWARM_CONFIG.enable_concrete_validation is True

    def test_resilience_defaults(self) -> None:
        assert DEFAULT_SWARM_CONFIG.worker_retries == 2
        assert DEFAULT_SWARM_CONFIG.max_dispatches_per_task == 5
        assert DEFAULT_SWARM_CONFIG.consecutive_timeout_limit == 3
        assert DEFAULT_SWARM_CONFIG.rate_limit_retries == 3
        assert DEFAULT_SWARM_CONFIG.enable_model_failover is True
        assert DEFAULT_SWARM_CONFIG.worker_stuck_threshold == 3

    def test_scheduling_defaults(self) -> None:
        assert DEFAULT_SWARM_CONFIG.file_conflict_strategy == FileConflictStrategy.CLAIM_BASED
        assert DEFAULT_SWARM_CONFIG.dispatch_stagger_ms == 1500
        assert DEFAULT_SWARM_CONFIG.dispatch_lease_stale_ms == 300_000
        assert DEFAULT_SWARM_CONFIG.retry_base_delay_ms == 5_000
        assert DEFAULT_SWARM_CONFIG.partial_dependency_threshold == 0.5
        assert DEFAULT_SWARM_CONFIG.artifact_aware_skip is True

    def test_throttle_default(self) -> None:
        assert DEFAULT_SWARM_CONFIG.throttle == "free"

    def test_hollow_termination_defaults(self) -> None:
        assert DEFAULT_SWARM_CONFIG.hollow_termination_ratio == 0.55
        assert DEFAULT_SWARM_CONFIG.hollow_termination_min_dispatches == 8
        assert DEFAULT_SWARM_CONFIG.hollow_output_threshold == 120
        assert DEFAULT_SWARM_CONFIG.enable_hollow_termination is False

    def test_feature_defaults(self) -> None:
        assert DEFAULT_SWARM_CONFIG.enable_planning is True
        assert DEFAULT_SWARM_CONFIG.enable_wave_review is True
        assert DEFAULT_SWARM_CONFIG.enable_verification is True
        assert DEFAULT_SWARM_CONFIG.enable_persistence is True
        assert DEFAULT_SWARM_CONFIG.state_dir == ".agent/swarm-state"

    def test_tool_defaults(self) -> None:
        assert DEFAULT_SWARM_CONFIG.tool_access_mode == "all"
        assert DEFAULT_SWARM_CONFIG.worker_enforcement_mode == "doomloop_only"

    def test_probe_defaults(self) -> None:
        assert DEFAULT_SWARM_CONFIG.probe_models is True
        assert DEFAULT_SWARM_CONFIG.probe_failure_strategy == ProbeFailureStrategy.WARN_AND_TRY
        assert DEFAULT_SWARM_CONFIG.probe_timeout_ms == 60_000

    def test_hierarchy_default(self) -> None:
        assert isinstance(DEFAULT_SWARM_CONFIG.hierarchy, HierarchyConfig)

    def test_auto_split_default(self) -> None:
        assert isinstance(DEFAULT_SWARM_CONFIG.auto_split, AutoSplitConfig)

    def test_completion_guard_default(self) -> None:
        assert isinstance(DEFAULT_SWARM_CONFIG.completion_guard, CompletionGuardConfig)

    def test_model_validation_default(self) -> None:
        assert isinstance(DEFAULT_SWARM_CONFIG.model_validation, ModelValidationConfig)

    def test_max_verification_retries_default(self) -> None:
        assert DEFAULT_SWARM_CONFIG.max_verification_retries == 2

    def test_paid_only_default(self) -> None:
        assert DEFAULT_SWARM_CONFIG.paid_only is False

    def test_task_types_default(self) -> None:
        assert DEFAULT_SWARM_CONFIG.task_types == {}

    def test_decomposition_priorities_default(self) -> None:
        assert DEFAULT_SWARM_CONFIG.decomposition_priorities is None

    def test_philosophy_default(self) -> None:
        assert DEFAULT_SWARM_CONFIG.philosophy == ""

    def test_codebase_context_default(self) -> None:
        assert DEFAULT_SWARM_CONFIG.codebase_context is None

    def test_resume_session_id_default(self) -> None:
        assert DEFAULT_SWARM_CONFIG.resume_session_id is None

    def test_custom_swarm_config(self) -> None:
        cfg = SwarmConfig(
            enabled=True,
            orchestrator_model="anthropic/claude-sonnet",
            max_concurrency=5,
            quality_threshold=4,
            paid_only=True,
        )
        assert cfg.max_concurrency == 5
        assert cfg.quality_threshold == 4
        assert cfg.paid_only is True

    def test_as_dict_roundtrip(self) -> None:
        cfg = SwarmConfig()
        d = asdict(cfg)
        assert isinstance(d, dict)
        assert d["enabled"] is True
        assert d["max_concurrency"] == 3


# ============================================================================
# Helpers: is_hollow_completion
# ============================================================================


class TestIsHollowCompletion:
    def test_zero_tool_calls_short_output(self) -> None:
        """Zero tool calls + short output -> True."""
        result = SpawnResult(success=True, output="ok", tool_calls=0)
        assert is_hollow_completion(result) is True

    def test_zero_tool_calls_empty_output(self) -> None:
        result = SpawnResult(success=True, output="", tool_calls=0)
        assert is_hollow_completion(result) is True

    def test_zero_tool_calls_boilerplate(self) -> None:
        """Zero tool calls + boilerplate in short output -> True."""
        result = SpawnResult(
            success=True,
            output="I'll help you with this task. Let me think about it.",
            tool_calls=0,
        )
        assert is_hollow_completion(result) is True

    def test_zero_tool_calls_boilerplate_all_indicators(self) -> None:
        """Each boilerplate indicator should trigger hollow detection."""
        for indicator in BOILERPLATE_INDICATORS:
            result = SpawnResult(
                success=True,
                output=f"{indicator} do something useful here.",
                tool_calls=0,
            )
            assert is_hollow_completion(result) is True, f"Failed for: {indicator}"

    def test_success_with_failure_indicators(self) -> None:
        """Success=True but output has failure language -> True."""
        result = SpawnResult(
            success=True,
            output="I was unable to complete the requested changes due to an error.",
            tool_calls=5,
        )
        assert is_hollow_completion(result) is True

    def test_each_failure_indicator(self) -> None:
        for indicator in FAILURE_INDICATORS:
            result = SpawnResult(
                success=True,
                output=f"Some prefix {indicator} some suffix text padding" * 3,
                tool_calls=3,
            )
            assert is_hollow_completion(result) is True, f"Failed for: {indicator}"

    def test_failure_indicator_not_triggered_when_not_success(self) -> None:
        """Failure indicators only matter when success=True."""
        result = SpawnResult(
            success=False,
            output="I was unable to complete the task. " * 10,
            tool_calls=5,
        )
        # success=False => check 3 does not apply. Output is long and has tool calls.
        # This should NOT be hollow (success=False skips check 3).
        assert is_hollow_completion(result) is False

    def test_requires_tool_calls_zero(self) -> None:
        """Task type requires tool calls but got zero -> True."""
        result = SpawnResult(
            success=True,
            output="I analyzed the code thoroughly and here is my comprehensive report. " * 20,
            tool_calls=0,
        )
        assert is_hollow_completion(result, task_type="implement") is True

    def test_requires_tool_calls_for_test_type(self) -> None:
        result = SpawnResult(
            success=True,
            output="Here are the test results " * 20,
            tool_calls=0,
        )
        assert is_hollow_completion(result, task_type="test") is True

    def test_no_requires_tool_calls_for_research(self) -> None:
        """Research does not require tool calls, so zero tool calls with long output is OK."""
        result = SpawnResult(
            success=True,
            output="Based on my analysis of the requirements, " * 50,
            tool_calls=0,
        )
        assert is_hollow_completion(result, task_type="research") is False

    def test_timeout_never_hollow(self) -> None:
        """tool_calls=-1 means timeout, never considered hollow."""
        result = SpawnResult(success=False, output="", tool_calls=-1)
        assert is_hollow_completion(result) is False

    def test_timeout_with_short_output_not_hollow(self) -> None:
        result = SpawnResult(success=True, output="x", tool_calls=-1)
        assert is_hollow_completion(result) is False

    def test_normal_successful_completion(self) -> None:
        """Normal output with tool calls -> False."""
        result = SpawnResult(
            success=True,
            output="Created src/main.py with the requested changes. All tests pass. " * 5,
            tool_calls=8,
        )
        assert is_hollow_completion(result) is False

    def test_normal_with_many_tool_calls(self) -> None:
        result = SpawnResult(
            success=True,
            output="Made changes",
            tool_calls=15,
        )
        assert is_hollow_completion(result) is False

    def test_long_output_no_tool_calls_no_boilerplate(self) -> None:
        """Long non-boilerplate output with zero tool calls for non-tool type."""
        result = SpawnResult(
            success=True,
            output="This is a detailed analysis result with no issues found. " * 30,
            tool_calls=0,
        )
        # No boilerplate, long output (>300 chars), no failure indicators
        assert is_hollow_completion(result, task_type="review") is False

    def test_custom_threshold_via_config(self) -> None:
        """SwarmConfig.hollow_output_threshold overrides default 120."""
        config = SwarmConfig(hollow_output_threshold=10)
        result = SpawnResult(success=True, output="short", tool_calls=0)
        assert is_hollow_completion(result, swarm_config=config) is True

        config2 = SwarmConfig(hollow_output_threshold=500)
        result2 = SpawnResult(success=True, output="x" * 200, tool_calls=0)
        assert is_hollow_completion(result2, swarm_config=config2) is True

    def test_high_threshold_prevents_short_output_hollow(self) -> None:
        config = SwarmConfig(hollow_output_threshold=5)
        result = SpawnResult(success=True, output="1234567890", tool_calls=0)
        # 10 chars > 5 threshold, so check 1 doesn't fire.
        # But check 2: < 300 chars, no boilerplate. Not hollow from check 2.
        # Check 3: success=True, no failure indicators.
        # => Not hollow
        assert is_hollow_completion(result, swarm_config=config) is False

    def test_unknown_task_type_no_config(self) -> None:
        """Unknown task type doesn't have a config, so check 4 doesn't fire."""
        result = SpawnResult(
            success=True,
            output="Did some work. " * 30,
            tool_calls=0,
        )
        assert is_hollow_completion(result, task_type="custom_nonexistent") is False

    def test_zero_tool_calls_boilerplate_but_long(self) -> None:
        """Boilerplate but output longer than 300 chars -> check 2 doesn't fire."""
        result = SpawnResult(
            success=True,
            output=("I'll help you " + "x" * 350),
            tool_calls=0,
        )
        # > 300 chars so check 2 won't fire.
        # check 1: > 120 chars, doesn't fire.
        # check 3: success=True but no failure indicators.
        assert is_hollow_completion(result) is False


# ============================================================================
# Helpers: has_future_intent_language
# ============================================================================


class TestHasFutureIntentLanguage:
    def test_will_create(self) -> None:
        assert has_future_intent_language("I will create the module") is True

    def test_will_implement(self) -> None:
        assert has_future_intent_language("I will implement the feature") is True

    def test_will_write(self) -> None:
        assert has_future_intent_language("I will write the tests") is True

    def test_need_to_create(self) -> None:
        assert has_future_intent_language("I need to create a new file") is True

    def test_next_steps(self) -> None:
        assert has_future_intent_language("The next steps are to refine") is True

    def test_ill_pattern(self) -> None:
        assert has_future_intent_language("I'll do this next") is True

    def test_let_me_create(self) -> None:
        assert has_future_intent_language("Let me create the file") is True

    def test_going_to(self) -> None:
        assert has_future_intent_language("I'm going to refactor the module") is True

    def test_will_need_to(self) -> None:
        assert has_future_intent_language("We will need to update the config") is True

    def test_should_implement(self) -> None:
        assert has_future_intent_language("We should implement caching") is True

    def test_will_create_done_no_future(self) -> None:
        """Future intent + completion signal -> False."""
        assert has_future_intent_language("I will create... done") is False

    def test_will_create_completed(self) -> None:
        assert has_future_intent_language("I will create the file. Completed successfully.") is False

    def test_will_create_created(self) -> None:
        assert has_future_intent_language("I will create it. Created the module.") is False

    def test_will_create_finished(self) -> None:
        assert has_future_intent_language("I will create it. Finished.") is False

    def test_will_create_implemented(self) -> None:
        assert has_future_intent_language("I will implement it. Implemented the feature.") is False

    def test_will_create_updated(self) -> None:
        assert has_future_intent_language("I will update the code. Updated successfully.") is False

    def test_will_create_wrote(self) -> None:
        assert has_future_intent_language("I will write tests. Wrote all tests.") is False

    def test_will_create_fixed(self) -> None:
        assert has_future_intent_language("I will fix the bug. Fixed.") is False

    def test_will_create_modified(self) -> None:
        assert has_future_intent_language("I will modify it. Modified the config.") is False

    def test_no_future_intent_past_tense(self) -> None:
        assert has_future_intent_language("Created the file") is False

    def test_no_future_intent_plain(self) -> None:
        assert has_future_intent_language("The function returns a list") is False

    def test_empty_string(self) -> None:
        assert has_future_intent_language("") is False

    def test_no_match_at_all(self) -> None:
        assert has_future_intent_language("Hello world, this is a simple text") is False

    def test_successfully_is_completion_signal(self) -> None:
        assert has_future_intent_language("I will create files. Done successfully.") is False


# ============================================================================
# Helpers: repo_looks_unscaffolded
# ============================================================================


class TestRepoLooksUnscaffolded:
    def test_empty_dir_is_unscaffolded(self, tmp_path: Any) -> None:
        assert repo_looks_unscaffolded(str(tmp_path)) is True

    def test_with_package_json_not_unscaffolded(self, tmp_path: Any) -> None:
        (tmp_path / "package.json").write_text("{}")
        assert repo_looks_unscaffolded(str(tmp_path)) is False

    def test_with_src_dir_not_unscaffolded(self, tmp_path: Any) -> None:
        (tmp_path / "src").mkdir()
        assert repo_looks_unscaffolded(str(tmp_path)) is False

    def test_with_both_not_unscaffolded(self, tmp_path: Any) -> None:
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "src").mkdir()
        assert repo_looks_unscaffolded(str(tmp_path)) is False

    def test_other_files_still_unscaffolded(self, tmp_path: Any) -> None:
        (tmp_path / "README.md").write_text("# hello")
        (tmp_path / "setup.py").write_text("")
        assert repo_looks_unscaffolded(str(tmp_path)) is True

    def test_src_file_not_dir_still_unscaffolded(self, tmp_path: Any) -> None:
        """A file named 'src' (not directory) doesn't count."""
        (tmp_path / "src").write_text("not a directory")
        assert repo_looks_unscaffolded(str(tmp_path)) is True


# ============================================================================
# Config Loader: parse_swarm_yaml
# ============================================================================


class TestParseSwarmYaml:
    def test_basic_key_value(self) -> None:
        result = parse_swarm_yaml("key: value")
        assert result == {"key": "value"}

    def test_nested_objects(self) -> None:
        yaml_str = """\
parent:
  child: 42
  grandchild:
    deep: true
"""
        result = parse_swarm_yaml(yaml_str)
        assert result["parent"]["child"] == 42
        assert result["parent"]["grandchild"]["deep"] is True

    def test_arrays(self) -> None:
        yaml_str = """\
items:
  - one
  - two
  - three
"""
        result = parse_swarm_yaml(yaml_str)
        assert result["items"] == ["one", "two", "three"]

    def test_boolean_coercion(self) -> None:
        result = parse_swarm_yaml("flag: true\nother: false")
        assert result["flag"] is True
        assert result["other"] is False

    def test_numeric_coercion(self) -> None:
        result = parse_swarm_yaml("count: 42\nrate: 0.5")
        assert result["count"] == 42
        assert result["rate"] == 0.5

    def test_null_coercion(self) -> None:
        result = parse_swarm_yaml("nothing: null\nalso: ~")
        # null values won't be "not None" so safe_load gives None
        assert result["nothing"] is None
        assert result["also"] is None

    def test_empty_content(self) -> None:
        assert parse_swarm_yaml("") == {}

    def test_none_content_equivalent(self) -> None:
        # YAML safe_load on whitespace returns None
        assert parse_swarm_yaml("   ") == {}

    def test_comments_stripped(self) -> None:
        result = parse_swarm_yaml("key: value  # this is a comment")
        assert result["key"] == "value"

    def test_quoted_strings(self) -> None:
        result = parse_swarm_yaml('msg: "true"')
        assert result["msg"] == "true"  # string, not bool

    def test_non_dict_returns_empty(self) -> None:
        # YAML that parses to a list
        assert parse_swarm_yaml("- item1\n- item2") == {}

    def test_non_dict_scalar_returns_empty(self) -> None:
        assert parse_swarm_yaml("just a string") == {}

    def test_complex_swarm_config(self) -> None:
        yaml_str = """\
models:
  orchestrator: anthropic/claude-sonnet
workers:
  - model: openai/gpt-4o
    count: 2
    capabilities:
      - code
      - review
budget:
  total_tokens: 1000000
  max_cost: 5.0
"""
        result = parse_swarm_yaml(yaml_str)
        assert result["models"]["orchestrator"] == "anthropic/claude-sonnet"
        assert len(result["workers"]) == 1  # raw YAML, not expanded
        assert result["budget"]["total_tokens"] == 1_000_000


# ============================================================================
# Config Loader: load_swarm_yaml_config
# ============================================================================


class TestLoadSwarmYamlConfig:
    def test_no_config_returns_none(self, tmp_path: Any) -> None:
        result = load_swarm_yaml_config(str(tmp_path))
        assert result is None

    def test_yaml_file(self, tmp_path: Any) -> None:
        attocode_dir = tmp_path / ".attocode"
        attocode_dir.mkdir()
        (attocode_dir / "swarm.yaml").write_text("max_concurrency: 5")
        result = load_swarm_yaml_config(str(tmp_path))
        assert result is not None
        assert result["max_concurrency"] == 5

    def test_yml_file(self, tmp_path: Any) -> None:
        attocode_dir = tmp_path / ".attocode"
        attocode_dir.mkdir()
        (attocode_dir / "swarm.yml").write_text("enabled: true")
        result = load_swarm_yaml_config(str(tmp_path))
        assert result is not None
        assert result["enabled"] is True

    def test_json_file(self, tmp_path: Any) -> None:
        attocode_dir = tmp_path / ".attocode"
        attocode_dir.mkdir()
        (attocode_dir / "swarm.json").write_text('{"quality_gates": false}')
        result = load_swarm_yaml_config(str(tmp_path))
        assert result is not None
        assert result["quality_gates"] is False

    def test_yaml_takes_priority_over_yml(self, tmp_path: Any) -> None:
        attocode_dir = tmp_path / ".attocode"
        attocode_dir.mkdir()
        (attocode_dir / "swarm.yaml").write_text("source: yaml")
        (attocode_dir / "swarm.yml").write_text("source: yml")
        result = load_swarm_yaml_config(str(tmp_path))
        assert result is not None
        assert result["source"] == "yaml"

    def test_yml_takes_priority_over_json(self, tmp_path: Any) -> None:
        attocode_dir = tmp_path / ".attocode"
        attocode_dir.mkdir()
        (attocode_dir / "swarm.yml").write_text("source: yml")
        (attocode_dir / "swarm.json").write_text('{"source": "json"}')
        result = load_swarm_yaml_config(str(tmp_path))
        assert result is not None
        assert result["source"] == "yml"

    def test_invalid_json_returns_none(self, tmp_path: Any) -> None:
        attocode_dir = tmp_path / ".attocode"
        attocode_dir.mkdir()
        (attocode_dir / "swarm.json").write_text("not valid json {{{")
        result = load_swarm_yaml_config(str(tmp_path))
        assert result is None

    def test_json_non_dict_returns_empty(self, tmp_path: Any) -> None:
        attocode_dir = tmp_path / ".attocode"
        attocode_dir.mkdir()
        (attocode_dir / "swarm.json").write_text("[1, 2, 3]")
        result = load_swarm_yaml_config(str(tmp_path))
        assert result == {}


# ============================================================================
# Config Loader: yaml_to_swarm_config
# ============================================================================


class TestYamlToSwarmConfig:
    def test_models_section(self) -> None:
        raw = {"models": {"orchestrator": "anthropic/claude-sonnet"}}
        cfg = yaml_to_swarm_config(raw, "default-model")
        assert cfg["orchestrator_model"] == "anthropic/claude-sonnet"

    def test_models_string(self) -> None:
        raw = {"models": "my-model-id"}
        cfg = yaml_to_swarm_config(raw, "default-model")
        assert cfg["orchestrator_model"] == "my-model-id"

    def test_models_planner(self) -> None:
        raw = {"models": {"orchestrator": "orch", "planner": "plan-model"}}
        cfg = yaml_to_swarm_config(raw, "default")
        assert cfg["planner_model"] == "plan-model"

    def test_models_quality_gate(self) -> None:
        raw = {"models": {"orchestrator": "orch", "quality_gate": "qg-model"}}
        cfg = yaml_to_swarm_config(raw, "default")
        assert cfg["quality_gate_model"] == "qg-model"

    def test_models_quality_gate_camel(self) -> None:
        raw = {"models": {"orchestrator": "orch", "qualityGate": "qg-camel"}}
        cfg = yaml_to_swarm_config(raw, "default")
        assert cfg["quality_gate_model"] == "qg-camel"

    def test_fallback_to_orchestrator_model(self) -> None:
        raw: dict[str, Any] = {}
        cfg = yaml_to_swarm_config(raw, "fallback-model")
        assert cfg["orchestrator_model"] == "fallback-model"

    def test_top_level_orchestrator_string_fallback(self) -> None:
        """Top-level 'orchestrator' is a fallback only when models section
        leaves orchestrator_model empty/falsy."""
        raw = {"models": {"orchestrator": ""}, "orchestrator": "top-level-model"}
        cfg = yaml_to_swarm_config(raw, "default")
        assert cfg["orchestrator_model"] == "top-level-model"

    def test_top_level_orchestrator_dict_fallback(self) -> None:
        raw = {"models": {"orchestrator": ""}, "orchestrator": {"model": "dict-model"}}
        cfg = yaml_to_swarm_config(raw, "default")
        assert cfg["orchestrator_model"] == "dict-model"

    def test_top_level_orchestrator_ignored_when_models_set(self) -> None:
        """When models section provides orchestrator, top-level key is ignored."""
        raw = {"models": {"orchestrator": "from-models"}, "orchestrator": "top-level"}
        cfg = yaml_to_swarm_config(raw, "default")
        assert cfg["orchestrator_model"] == "from-models"

    def test_top_level_orchestrator_not_used_when_no_models_section(self) -> None:
        """Without an explicit models section, orchestrator_model arg is used,
        not the top-level 'orchestrator' key (models defaults to empty dict
        which resolves to the function's orchestrator_model parameter)."""
        raw = {"orchestrator": "top-level-model"}
        cfg = yaml_to_swarm_config(raw, "default")
        # The models section defaults to {} -> orchestrator defaults to "default"
        assert cfg["orchestrator_model"] == "default"

    def test_workers_basic(self) -> None:
        raw = {
            "workers": [
                {"model": "openai/gpt-4o", "name": "coder"},
            ],
        }
        cfg = yaml_to_swarm_config(raw, "orch")
        assert "workers" in cfg
        assert len(cfg["workers"]) == 1
        assert cfg["workers"][0]["model"] == "openai/gpt-4o"

    def test_workers_with_count(self) -> None:
        raw = {
            "workers": [
                {"model": "openai/gpt-4o", "name": "worker", "count": 3},
            ],
        }
        cfg = yaml_to_swarm_config(raw, "orch")
        assert len(cfg["workers"]) == 3
        assert cfg["workers"][0]["name"] == "worker-0"
        assert cfg["workers"][2]["name"] == "worker-2"

    def test_workers_with_capabilities(self) -> None:
        raw = {
            "workers": [
                {
                    "model": "m1",
                    "name": "reviewer",
                    "capabilities": ["review", "research"],
                },
            ],
        }
        cfg = yaml_to_swarm_config(raw, "orch")
        caps = cfg["workers"][0]["capabilities"]
        assert WorkerCapability.REVIEW in caps
        assert WorkerCapability.RESEARCH in caps

    def test_workers_with_single_capability(self) -> None:
        raw = {
            "workers": [{"model": "m1", "name": "w", "capability": "test"}],
        }
        cfg = yaml_to_swarm_config(raw, "orch")
        assert WorkerCapability.TEST in cfg["workers"][0]["capabilities"]

    def test_workers_non_dict_skipped(self) -> None:
        raw = {"workers": ["invalid", {"model": "m1", "name": "w"}]}
        cfg = yaml_to_swarm_config(raw, "orch")
        assert len(cfg["workers"]) == 1

    def test_budget_section(self) -> None:
        raw = {
            "budget": {
                "total_tokens": 2_000_000,
                "max_cost": 3.5,
                "max_concurrency": 4,
            },
        }
        cfg = yaml_to_swarm_config(raw, "orch")
        assert cfg["total_budget"] == 2_000_000
        assert cfg["max_cost"] == 3.5
        assert cfg["max_concurrency"] == 4

    def test_budget_camel_case(self) -> None:
        raw = {
            "budget": {
                "totalTokens": 1_500_000,
                "maxCost": 7.0,
                "maxConcurrency": 6,
            },
        }
        cfg = yaml_to_swarm_config(raw, "orch")
        assert cfg["total_budget"] == 1_500_000
        assert cfg["max_cost"] == 7.0
        assert cfg["max_concurrency"] == 6

    def test_top_level_max_concurrency(self) -> None:
        raw = {"max_concurrency": 8}
        cfg = yaml_to_swarm_config(raw, "orch")
        assert cfg["max_concurrency"] == 8

    def test_top_level_max_concurrency_camel(self) -> None:
        raw = {"maxConcurrency": 10}
        cfg = yaml_to_swarm_config(raw, "orch")
        assert cfg["max_concurrency"] == 10

    def test_budget_max_concurrency_takes_priority_over_top_level(self) -> None:
        raw = {
            "budget": {"max_concurrency": 4},
            "max_concurrency": 8,
        }
        cfg = yaml_to_swarm_config(raw, "orch")
        assert cfg["max_concurrency"] == 4

    def test_quality_section_dict(self) -> None:
        raw = {"quality": {"enabled": True, "threshold": 4}}
        cfg = yaml_to_swarm_config(raw, "orch")
        assert cfg["quality_gates"] is True
        assert cfg["quality_threshold"] == 4

    def test_quality_section_bool(self) -> None:
        raw = {"quality": False}
        cfg = yaml_to_swarm_config(raw, "orch")
        assert cfg["quality_gates"] is False

    def test_quality_gates_top_level(self) -> None:
        raw = {"qualityGates": True}
        cfg = yaml_to_swarm_config(raw, "orch")
        assert cfg["quality_gates"] is True

    def test_resilience_section(self) -> None:
        raw = {
            "resilience": {
                "worker_retries": 5,
                "model_failover": False,
            },
        }
        cfg = yaml_to_swarm_config(raw, "orch")
        assert cfg["worker_retries"] == 5
        assert cfg["enable_model_failover"] is False

    def test_resilience_camel_case(self) -> None:
        raw = {
            "resilience": {
                "workerRetries": 4,
                "modelFailover": True,
            },
        }
        cfg = yaml_to_swarm_config(raw, "orch")
        assert cfg["worker_retries"] == 4
        assert cfg["enable_model_failover"] is True

    def test_features_section(self) -> None:
        raw = {
            "features": {
                "planning": False,
                "wave_review": True,
                "verification": False,
                "persistence": True,
            },
        }
        cfg = yaml_to_swarm_config(raw, "orch")
        assert cfg["enable_planning"] is False
        assert cfg["enable_wave_review"] is True
        assert cfg["enable_verification"] is False
        assert cfg["enable_persistence"] is True

    def test_features_camel_case(self) -> None:
        raw = {"features": {"waveReview": False}}
        cfg = yaml_to_swarm_config(raw, "orch")
        assert cfg["enable_wave_review"] is False

    def test_hierarchy_section(self) -> None:
        raw = {
            "hierarchy": {
                "manager": {"model": "anthropic/claude-opus"},
                "judge": "openai/gpt-4o",
            },
        }
        cfg = yaml_to_swarm_config(raw, "orch")
        assert cfg["hierarchy"]["manager"] == {"model": "anthropic/claude-opus"}
        assert cfg["hierarchy"]["judge"] == {"model": "openai/gpt-4o"}

    def test_throttle(self) -> None:
        raw = {"throttle": "paid"}
        cfg = yaml_to_swarm_config(raw, "orch")
        assert cfg["throttle"] == "paid"

    def test_throttle_false(self) -> None:
        raw = {"throttle": False}
        cfg = yaml_to_swarm_config(raw, "orch")
        assert cfg["throttle"] is False

    def test_paid_only(self) -> None:
        raw = {"paid_only": True}
        cfg = yaml_to_swarm_config(raw, "orch")
        assert cfg["paid_only"] is True

    def test_paid_only_camel(self) -> None:
        raw = {"paidOnly": True}
        cfg = yaml_to_swarm_config(raw, "orch")
        assert cfg["paid_only"] is True

    def test_auto_split(self) -> None:
        raw = {"auto_split": {"enabled": False, "max_subtasks": 6}}
        cfg = yaml_to_swarm_config(raw, "orch")
        assert cfg["auto_split"]["enabled"] is False
        assert cfg["auto_split"]["max_subtasks"] == 6

    def test_auto_split_camel(self) -> None:
        raw = {"autoSplit": {"enabled": True}}
        cfg = yaml_to_swarm_config(raw, "orch")
        assert cfg["auto_split"]["enabled"] is True

    def test_completion_guard(self) -> None:
        raw = {"completion_guard": {"reject_future_intent_outputs": False}}
        cfg = yaml_to_swarm_config(raw, "orch")
        assert cfg["completion_guard"]["reject_future_intent_outputs"] is False

    def test_completion_guard_camel(self) -> None:
        raw = {"completionGuard": {"reject_future_intent_outputs": True}}
        cfg = yaml_to_swarm_config(raw, "orch")
        assert cfg["completion_guard"]["reject_future_intent_outputs"] is True

    def test_direct_mappings_snake(self) -> None:
        raw = {
            "worker_timeout": 60_000,
            "worker_max_iterations": 20,
            "dispatch_stagger_ms": 2000,
            "state_dir": "/tmp/swarm",
            "philosophy": "move fast",
            "probe_models": False,
            "hollow_termination_ratio": 0.8,
            "enable_hollow_termination": True,
        }
        cfg = yaml_to_swarm_config(raw, "orch")
        assert cfg["worker_timeout"] == 60_000
        assert cfg["worker_max_iterations"] == 20
        assert cfg["dispatch_stagger_ms"] == 2000
        assert cfg["state_dir"] == "/tmp/swarm"
        assert cfg["philosophy"] == "move fast"
        assert cfg["probe_models"] is False
        assert cfg["hollow_termination_ratio"] == 0.8
        assert cfg["enable_hollow_termination"] is True

    def test_direct_mappings_camel(self) -> None:
        raw = {
            "workerTimeout": 30_000,
            "workerMaxIterations": 10,
            "dispatchStaggerMs": 1000,
            "stateDir": "/tmp/s",
            "probeModels": True,
            "hollowTerminationRatio": 0.6,
            "enableHollowTermination": False,
        }
        cfg = yaml_to_swarm_config(raw, "orch")
        assert cfg["worker_timeout"] == 30_000
        assert cfg["worker_max_iterations"] == 10
        assert cfg["dispatch_stagger_ms"] == 1000
        assert cfg["state_dir"] == "/tmp/s"
        assert cfg["probe_models"] is True
        assert cfg["hollow_termination_ratio"] == 0.6
        assert cfg["enable_hollow_termination"] is False

    def test_empty_raw(self) -> None:
        cfg = yaml_to_swarm_config({}, "default-model")
        assert cfg["orchestrator_model"] == "default-model"


# ============================================================================
# Config Loader: merge_swarm_configs
# ============================================================================


class TestMergeSwarmConfigs:
    def test_defaults_only(self) -> None:
        result = merge_swarm_configs(DEFAULT_SWARM_CONFIG, None, {})
        assert result.max_concurrency == 3
        assert result.quality_gates is True

    def test_yaml_overrides_defaults(self) -> None:
        yaml_cfg = {"max_concurrency": 5, "quality_gates": False}
        result = merge_swarm_configs(DEFAULT_SWARM_CONFIG, yaml_cfg, {})
        assert result.max_concurrency == 5
        assert result.quality_gates is False

    def test_cli_overrides_yaml(self) -> None:
        yaml_cfg = {"max_concurrency": 5}
        cli = {"max_concurrency": 8}
        result = merge_swarm_configs(DEFAULT_SWARM_CONFIG, yaml_cfg, cli)
        assert result.max_concurrency == 8

    def test_three_way_merge(self) -> None:
        defaults = SwarmConfig(max_concurrency=3, quality_threshold=3)
        yaml_cfg = {"max_concurrency": 5}
        cli = {"quality_threshold": 4}
        result = merge_swarm_configs(defaults, yaml_cfg, cli)
        assert result.max_concurrency == 5  # from yaml
        assert result.quality_threshold == 4  # from cli

    def test_orchestrator_model_explicit(self) -> None:
        """CLI orchestrator_model only wins when orchestrator_model_explicit=True."""
        yaml_cfg = {"orchestrator_model": "yaml-model"}
        cli = {"orchestrator_model": "cli-model", "orchestrator_model_explicit": True}
        result = merge_swarm_configs(DEFAULT_SWARM_CONFIG, yaml_cfg, cli)
        assert result.orchestrator_model == "cli-model"

    def test_orchestrator_model_not_explicit(self) -> None:
        yaml_cfg = {"orchestrator_model": "yaml-model"}
        cli = {"orchestrator_model": "cli-model"}
        result = merge_swarm_configs(DEFAULT_SWARM_CONFIG, yaml_cfg, cli)
        assert result.orchestrator_model == "yaml-model"

    def test_orchestrator_model_explicit_false(self) -> None:
        yaml_cfg = {"orchestrator_model": "yaml-model"}
        cli = {"orchestrator_model": "cli-model", "orchestrator_model_explicit": False}
        result = merge_swarm_configs(DEFAULT_SWARM_CONFIG, yaml_cfg, cli)
        assert result.orchestrator_model == "yaml-model"

    def test_paid_only_defaults_throttle(self) -> None:
        """When paid_only=True and yaml doesn't set throttle, throttle -> 'paid'."""
        cli = {"paid_only": True}
        result = merge_swarm_configs(DEFAULT_SWARM_CONFIG, None, cli)
        assert result.throttle == "paid"

    def test_paid_only_yaml_throttle_preserved(self) -> None:
        """When yaml sets throttle, paid_only doesn't override it."""
        yaml_cfg = {"throttle": "free"}
        cli = {"paid_only": True}
        result = merge_swarm_configs(DEFAULT_SWARM_CONFIG, yaml_cfg, cli)
        assert result.throttle == "free"

    def test_none_cli_values_ignored(self) -> None:
        cli = {"max_concurrency": None, "quality_threshold": 4}
        result = merge_swarm_configs(DEFAULT_SWARM_CONFIG, None, cli)
        assert result.max_concurrency == 3  # default, not overridden
        assert result.quality_threshold == 4

    def test_workers_from_yaml(self) -> None:
        yaml_cfg = {
            "workers": [
                {"name": "w1", "model": "m1", "capabilities": [WorkerCapability.CODE]},
            ],
        }
        result = merge_swarm_configs(DEFAULT_SWARM_CONFIG, yaml_cfg, {})
        assert len(result.workers) == 1
        assert isinstance(result.workers[0], SwarmWorkerSpec)
        assert result.workers[0].name == "w1"

    def test_hierarchy_from_yaml(self) -> None:
        yaml_cfg = {
            "hierarchy": {
                "manager": {"model": "mgr-model"},
                "judge": {"model": "judge-model"},
            },
        }
        result = merge_swarm_configs(DEFAULT_SWARM_CONFIG, yaml_cfg, {})
        assert isinstance(result.hierarchy, HierarchyConfig)
        assert result.hierarchy.manager.model == "mgr-model"
        assert result.hierarchy.judge.model == "judge-model"

    def test_auto_split_from_yaml(self) -> None:
        yaml_cfg = {"auto_split": {"enabled": False, "max_subtasks": 2}}
        result = merge_swarm_configs(DEFAULT_SWARM_CONFIG, yaml_cfg, {})
        assert isinstance(result.auto_split, AutoSplitConfig)
        assert result.auto_split.enabled is False
        assert result.auto_split.max_subtasks == 2

    def test_completion_guard_from_yaml(self) -> None:
        yaml_cfg = {"completion_guard": {"reject_future_intent_outputs": False}}
        result = merge_swarm_configs(DEFAULT_SWARM_CONFIG, yaml_cfg, {})
        assert isinstance(result.completion_guard, CompletionGuardConfig)
        assert result.completion_guard.reject_future_intent_outputs is False

    def test_returns_swarm_config_type(self) -> None:
        result = merge_swarm_configs(DEFAULT_SWARM_CONFIG, None, {})
        assert isinstance(result, SwarmConfig)


# ============================================================================
# Config Loader: normalize_capabilities
# ============================================================================


class TestNormalizeCapabilities:
    def test_direct_enum_values(self) -> None:
        result = normalize_capabilities(["code", "review", "test"])
        assert result == [WorkerCapability.CODE, WorkerCapability.REVIEW, WorkerCapability.TEST]

    def test_alias_refactor(self) -> None:
        result = normalize_capabilities(["refactor"])
        assert result == [WorkerCapability.CODE]

    def test_alias_implement(self) -> None:
        result = normalize_capabilities(["implement"])
        assert result == [WorkerCapability.CODE]

    def test_alias_coding(self) -> None:
        result = normalize_capabilities(["coding"])
        assert result == [WorkerCapability.CODE]

    def test_alias_writing(self) -> None:
        result = normalize_capabilities(["writing"])
        assert result == [WorkerCapability.WRITE]

    def test_alias_synthesis(self) -> None:
        result = normalize_capabilities(["synthesis"])
        assert result == [WorkerCapability.WRITE]

    def test_alias_merge(self) -> None:
        result = normalize_capabilities(["merge"])
        assert result == [WorkerCapability.WRITE]

    def test_alias_docs(self) -> None:
        result = normalize_capabilities(["docs"])
        assert result == [WorkerCapability.DOCUMENT]

    def test_alias_testing(self) -> None:
        result = normalize_capabilities(["testing"])
        assert result == [WorkerCapability.TEST]

    def test_alias_reviewing(self) -> None:
        result = normalize_capabilities(["reviewing"])
        assert result == [WorkerCapability.REVIEW]

    def test_alias_researching(self) -> None:
        result = normalize_capabilities(["researching"])
        assert result == [WorkerCapability.RESEARCH]

    def test_unknown_values_dropped(self) -> None:
        result = normalize_capabilities(["unknown_cap", "nonsense"])
        # Falls back to [CODE]
        assert result == [WorkerCapability.CODE]

    def test_empty_fallback_to_code(self) -> None:
        result = normalize_capabilities([])
        assert result == [WorkerCapability.CODE]

    def test_deduplication(self) -> None:
        result = normalize_capabilities(["code", "code", "refactor", "implement"])
        assert result == [WorkerCapability.CODE]

    def test_mixed_valid_and_invalid(self) -> None:
        result = normalize_capabilities(["review", "invalid", "test"])
        assert result == [WorkerCapability.REVIEW, WorkerCapability.TEST]

    def test_case_insensitive(self) -> None:
        result = normalize_capabilities(["CODE", "Review", "TEST"])
        assert result == [WorkerCapability.CODE, WorkerCapability.REVIEW, WorkerCapability.TEST]

    def test_whitespace_stripped(self) -> None:
        result = normalize_capabilities(["  code  ", " review "])
        assert result == [WorkerCapability.CODE, WorkerCapability.REVIEW]

    def test_all_aliases_mapped(self) -> None:
        """Every alias in _CAPABILITY_ALIASES should be recognized."""
        from attocode.integrations.swarm.config_loader import _CAPABILITY_ALIASES

        for alias, expected_cap in _CAPABILITY_ALIASES.items():
            result = normalize_capabilities([alias])
            assert expected_cap in result, f"Alias '{alias}' not mapping to {expected_cap}"


# ============================================================================
# Config Loader: normalize_swarm_model_config
# ============================================================================


class TestNormalizeSwarmModelConfig:
    def test_valid_models_no_warnings(self) -> None:
        cfg = SwarmConfig(
            orchestrator_model="anthropic/claude-sonnet",
            workers=[
                SwarmWorkerSpec(name="w1", model="openai/gpt-4o"),
            ],
        )
        result, warnings = normalize_swarm_model_config(cfg)
        assert len(warnings) == 0
        assert result.orchestrator_model == "anthropic/claude-sonnet"

    def test_bare_claude_auto_corrected(self) -> None:
        cfg = SwarmConfig(orchestrator_model="claude-sonnet-4-20250514")
        result, warnings = normalize_swarm_model_config(cfg)
        assert result.orchestrator_model == "anthropic/claude-sonnet-4-20250514"
        assert len(warnings) == 1
        assert "auto-corrected" in warnings[0]

    def test_bare_gpt_auto_corrected(self) -> None:
        cfg = SwarmConfig(
            workers=[SwarmWorkerSpec(name="w1", model="gpt-4o")],
        )
        result, warnings = normalize_swarm_model_config(cfg)
        assert result.workers[0].model == "openai/gpt-4o"
        assert len(warnings) == 1

    def test_bare_o1_auto_corrected(self) -> None:
        cfg = SwarmConfig(
            workers=[SwarmWorkerSpec(name="w1", model="o1-mini")],
        )
        result, warnings = normalize_swarm_model_config(cfg)
        assert result.workers[0].model == "openai/o1-mini"

    def test_bare_gemini_auto_corrected(self) -> None:
        cfg = SwarmConfig(planner_model="gemini-pro")
        result, warnings = normalize_swarm_model_config(cfg)
        assert result.planner_model == "google/gemini-pro"

    def test_bare_llama_auto_corrected(self) -> None:
        cfg = SwarmConfig(quality_gate_model="llama-3-70b")
        result, warnings = normalize_swarm_model_config(cfg)
        assert result.quality_gate_model == "meta-llama/llama-3-70b"

    def test_bare_deepseek_auto_corrected(self) -> None:
        cfg = SwarmConfig(orchestrator_model="deepseek-v3")
        result, warnings = normalize_swarm_model_config(cfg)
        assert result.orchestrator_model == "deepseek/deepseek-v3"

    def test_bare_mistral_auto_corrected(self) -> None:
        cfg = SwarmConfig(orchestrator_model="mistral-large")
        result, warnings = normalize_swarm_model_config(cfg)
        assert result.orchestrator_model == "mistralai/mistral-large"

    def test_bare_qwen_auto_corrected(self) -> None:
        cfg = SwarmConfig(orchestrator_model="qwen-2.5-72b")
        result, warnings = normalize_swarm_model_config(cfg)
        assert result.orchestrator_model == "qwen/qwen-2.5-72b"

    def test_bare_command_auto_corrected(self) -> None:
        cfg = SwarmConfig(orchestrator_model="command-r-plus")
        result, warnings = normalize_swarm_model_config(cfg)
        assert result.orchestrator_model == "cohere/command-r-plus"

    def test_unknown_bare_model_unchanged(self) -> None:
        cfg = SwarmConfig(orchestrator_model="some-custom-model")
        result, warnings = normalize_swarm_model_config(cfg)
        assert result.orchestrator_model == "some-custom-model"
        assert len(warnings) == 0

    def test_empty_model_unchanged(self) -> None:
        cfg = SwarmConfig(orchestrator_model="")
        result, warnings = normalize_swarm_model_config(cfg)
        assert result.orchestrator_model == ""
        assert len(warnings) == 0

    def test_hierarchy_models_validated(self) -> None:
        cfg = SwarmConfig(
            hierarchy=HierarchyConfig(
                manager=HierarchyRoleConfig(model="claude-opus"),
                judge=HierarchyRoleConfig(model="gpt-4"),
            ),
        )
        result, warnings = normalize_swarm_model_config(cfg)
        assert result.hierarchy.manager.model == "anthropic/claude-opus"
        assert result.hierarchy.judge.model == "openai/gpt-4"
        assert len(warnings) == 2

    def test_hierarchy_empty_model_no_warning(self) -> None:
        cfg = SwarmConfig(
            hierarchy=HierarchyConfig(
                manager=HierarchyRoleConfig(model=None),
                judge=HierarchyRoleConfig(model=None),
            ),
        )
        _, warnings = normalize_swarm_model_config(cfg)
        assert len(warnings) == 0

    def test_multiple_workers_validated(self) -> None:
        cfg = SwarmConfig(
            workers=[
                SwarmWorkerSpec(name="w1", model="claude-sonnet"),
                SwarmWorkerSpec(name="w2", model="openai/gpt-4o"),
                SwarmWorkerSpec(name="w3", model="gemini-pro"),
            ],
        )
        result, warnings = normalize_swarm_model_config(cfg)
        assert result.workers[0].model == "anthropic/claude-sonnet"
        assert result.workers[1].model == "openai/gpt-4o"  # already valid
        assert result.workers[2].model == "google/gemini-pro"
        assert len(warnings) == 2  # w1 and w3


# ============================================================================
# Config Loader: _to_snake and _guess_provider_prefix (internal helpers)
# ============================================================================


class TestToSnake:
    def test_already_snake(self) -> None:
        assert _to_snake("max_concurrency") == "max_concurrency"

    def test_camel_case(self) -> None:
        assert _to_snake("maxConcurrency") == "max_concurrency"

    def test_single_word(self) -> None:
        assert _to_snake("model") == "model"

    def test_starts_lower(self) -> None:
        assert _to_snake("workerTimeout") == "worker_timeout"

    def test_multiple_caps(self) -> None:
        assert _to_snake("enableHTTPProxy") == "enable_h_t_t_p_proxy"


class TestGuessProviderPrefix:
    def test_claude(self) -> None:
        assert _guess_provider_prefix("claude-sonnet") == "anthropic/claude-sonnet"

    def test_gpt(self) -> None:
        assert _guess_provider_prefix("gpt-4o") == "openai/gpt-4o"

    def test_o1(self) -> None:
        assert _guess_provider_prefix("o1-mini") == "openai/o1-mini"

    def test_o3(self) -> None:
        assert _guess_provider_prefix("o3-pro") == "openai/o3-pro"

    def test_o4(self) -> None:
        assert _guess_provider_prefix("o4-mini") == "openai/o4-mini"

    def test_gemini(self) -> None:
        assert _guess_provider_prefix("gemini-pro") == "google/gemini-pro"

    def test_llama(self) -> None:
        assert _guess_provider_prefix("llama-3-70b") == "meta-llama/llama-3-70b"

    def test_qwen(self) -> None:
        assert _guess_provider_prefix("qwen-2.5") == "qwen/qwen-2.5"

    def test_deepseek(self) -> None:
        assert _guess_provider_prefix("deepseek-chat") == "deepseek/deepseek-chat"

    def test_command(self) -> None:
        assert _guess_provider_prefix("command-r") == "cohere/command-r"

    def test_mistral(self) -> None:
        assert _guess_provider_prefix("mistral-large") == "mistralai/mistral-large"

    def test_ministral(self) -> None:
        assert _guess_provider_prefix("ministral-8b") == "mistralai/ministral-8b"

    def test_unknown_returns_as_is(self) -> None:
        assert _guess_provider_prefix("some-custom") == "some-custom"

    def test_already_prefixed_not_changed(self) -> None:
        # This function doesn't check for existing prefix, but if "/" is there
        # the caller (_validate_model) short-circuits before calling this.
        # Still, no harm in testing the raw function.
        result = _guess_provider_prefix("anthropic/claude-sonnet")
        # "anthropic/claude-sonnet" doesn't start with any hints after lowering
        # Actually it does! "anthropic" doesn't match any hint but it doesn't
        # start with claude/gpt/etc., so it's returned as-is... wait no.
        # It doesn't start with any of the hints. Let's just verify.
        # The string starts with "anthropic" which isn't in hints.
        assert result == "anthropic/claude-sonnet"

    def test_case_insensitive_matching(self) -> None:
        assert _guess_provider_prefix("Claude-Opus") == "anthropic/Claude-Opus"
        assert _guess_provider_prefix("GPT-4") == "openai/GPT-4"


# ============================================================================
# Callback Types (ensure they are importable)
# ============================================================================


class TestCallbackTypes:
    def test_swarm_event_listener_importable(self) -> None:
        from attocode.integrations.swarm.types import SwarmEventListener
        assert SwarmEventListener is not None

    def test_spawn_agent_fn_importable(self) -> None:
        from attocode.integrations.swarm.types import SpawnAgentFn
        assert SpawnAgentFn is not None
