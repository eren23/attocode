"""Swarm system types and configuration.

Defines all types for the multi-agent swarm orchestration system:
SwarmConfig, SwarmTask, SwarmTaskResult, SwarmCheckpoint, events, etc.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


# =============================================================================
# Enums
# =============================================================================


class SwarmTaskStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    DISPATCHED = "dispatched"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    DECOMPOSED = "decomposed"


class TaskFailureMode(StrEnum):
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate-limit"
    ERROR = "error"
    QUALITY = "quality"
    HOLLOW = "hollow"
    CASCADE = "cascade"
    RECOVERABLE = "recoverable"
    TERMINAL = "terminal"


class WorkerCapability(StrEnum):
    CODE = "code"
    RESEARCH = "research"
    REVIEW = "review"
    TEST = "test"
    DOCUMENT = "document"
    WRITE = "write"


class WorkerRole(StrEnum):
    EXECUTOR = "executor"
    MANAGER = "manager"
    JUDGE = "judge"


class SubtaskType(StrEnum):
    RESEARCH = "research"
    ANALYSIS = "analysis"
    DESIGN = "design"
    IMPLEMENT = "implement"
    TEST = "test"
    REFACTOR = "refactor"
    REVIEW = "review"
    DOCUMENT = "document"
    INTEGRATE = "integrate"
    DEPLOY = "deploy"
    MERGE = "merge"


class SwarmPhase(StrEnum):
    IDLE = "idle"
    DECOMPOSING = "decomposing"
    SCHEDULING = "scheduling"
    PLANNING = "planning"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    SYNTHESIZING = "synthesizing"
    COMPLETED = "completed"
    FAILED = "failed"


class FileConflictStrategy(StrEnum):
    CLAIM_BASED = "claim-based"
    SERIALIZE = "serialize"


class ProbeFailureStrategy(StrEnum):
    ABORT = "abort"
    WARN_AND_TRY = "warn-and-try"


# =============================================================================
# Task Type Configuration
# =============================================================================


@dataclass
class TaskTypeConfig:
    """Configuration for a task type."""

    capability: WorkerCapability
    requires_tool_calls: bool
    prompt_template: str  # 'code' | 'research' | 'synthesis' | 'document'
    timeout: int  # Seconds
    min_tokens: int = 20_000
    max_tokens: int = 80_000


BUILTIN_TASK_TYPE_CONFIGS: dict[str, TaskTypeConfig] = {
    "research": TaskTypeConfig(WorkerCapability.RESEARCH, False, "research", 300, 20_000, 80_000),
    "analysis": TaskTypeConfig(WorkerCapability.RESEARCH, False, "research", 300, 20_000, 80_000),
    "design": TaskTypeConfig(WorkerCapability.RESEARCH, False, "research", 300, 20_000, 80_000),
    "implement": TaskTypeConfig(WorkerCapability.CODE, True, "code", 300, 40_000, 150_000),
    "test": TaskTypeConfig(WorkerCapability.TEST, True, "code", 240, 20_000, 60_000),
    "refactor": TaskTypeConfig(WorkerCapability.CODE, True, "code", 240, 30_000, 100_000),
    "review": TaskTypeConfig(WorkerCapability.REVIEW, False, "research", 240, 15_000, 50_000),
    "document": TaskTypeConfig(WorkerCapability.DOCUMENT, True, "document", 240, 15_000, 50_000),
    "integrate": TaskTypeConfig(WorkerCapability.CODE, True, "code", 300, 30_000, 100_000),
    "deploy": TaskTypeConfig(WorkerCapability.CODE, True, "code", 240, 20_000, 60_000),
    "merge": TaskTypeConfig(WorkerCapability.WRITE, False, "synthesis", 180, 10_000, 30_000),
}


# =============================================================================
# Worker Spec
# =============================================================================


@dataclass
class SwarmWorkerSpec:
    """Specification for a swarm worker."""

    name: str
    model: str
    capabilities: list[WorkerCapability] = field(default_factory=lambda: [WorkerCapability.CODE])
    context_window: int = 128_000
    persona: str = ""
    role: WorkerRole = WorkerRole.EXECUTOR
    max_tokens: int = 50_000
    policy_profile: str = ""
    allowed_tools: list[str] | None = None
    denied_tools: list[str] | None = None
    extra_tools: list[str] | None = None
    prompt_tier: str = "full"  # 'full' | 'reduced' | 'minimal'


# =============================================================================
# Auto-Split Config
# =============================================================================


@dataclass
class AutoSplitConfig:
    """Configuration for automatic task splitting."""

    enabled: bool = True
    complexity_floor: int = 6
    splittable_types: list[str] = field(
        default_factory=lambda: ["implement", "refactor", "test"]
    )
    max_subtasks: int = 4


# =============================================================================
# Completion Guard Config
# =============================================================================


@dataclass
class CompletionGuardConfig:
    """Configuration for completion guards."""

    require_concrete_artifacts_for_action_tasks: bool = True
    reject_future_intent_outputs: bool = True


# =============================================================================
# Model Validation Config
# =============================================================================


@dataclass
class ModelValidationConfig:
    """Configuration for model ID validation."""

    mode: str = "autocorrect"  # 'strict' | 'autocorrect' | 'skip'
    on_invalid: str = "warn"  # 'warn' | 'error'


# =============================================================================
# Hierarchy Config
# =============================================================================


@dataclass
class HierarchyRoleConfig:
    """Config for a hierarchy role."""

    model: str | None = None


@dataclass
class HierarchyConfig:
    """Configuration for role hierarchy."""

    manager: HierarchyRoleConfig = field(default_factory=HierarchyRoleConfig)
    judge: HierarchyRoleConfig = field(default_factory=HierarchyRoleConfig)


# =============================================================================
# SwarmConfig
# =============================================================================


@dataclass
class SwarmConfig:
    """Complete swarm configuration."""

    enabled: bool = True
    orchestrator_model: str = ""
    workers: list[SwarmWorkerSpec] = field(default_factory=list)

    # Concurrency & budget
    max_concurrency: int = 3
    total_budget: int = 5_000_000  # tokens
    max_cost: float = 10.0  # USD
    orchestrator_reserve_ratio: float = 0.15
    max_tokens_per_worker: int = 50_000
    worker_timeout: int = 120_000  # ms
    worker_max_iterations: int = 15

    # Quality
    quality_gates: bool = True
    quality_threshold: int = 3  # 1-5
    quality_gate_model: str = ""
    enable_concrete_validation: bool = True

    # Retry & resilience
    worker_retries: int = 2
    max_dispatches_per_task: int = 5
    consecutive_timeout_limit: int = 3
    rate_limit_retries: int = 3
    enable_model_failover: bool = True
    worker_stuck_threshold: int = 3

    # Scheduling
    file_conflict_strategy: FileConflictStrategy = FileConflictStrategy.CLAIM_BASED
    dispatch_stagger_ms: int = 1500
    dispatch_lease_stale_ms: int = 300_000  # 5 min
    retry_base_delay_ms: int = 5_000
    partial_dependency_threshold: float = 0.5
    artifact_aware_skip: bool = True

    # Throttle
    throttle: str | bool = "free"  # 'free' | 'paid' | false

    # Hollow termination
    hollow_termination_ratio: float = 0.55
    hollow_termination_min_dispatches: int = 8
    hollow_output_threshold: int = 120  # chars
    enable_hollow_termination: bool = False

    # Features
    enable_planning: bool = True
    enable_wave_review: bool = True
    enable_verification: bool = True
    enable_persistence: bool = True
    state_dir: str = ".agent/swarm-state"

    # Tools & permissions
    tool_access_mode: str = "all"  # 'whitelist' | 'all'
    worker_enforcement_mode: str = "doomloop_only"

    # Model probing
    probe_models: bool = True
    probe_failure_strategy: ProbeFailureStrategy = ProbeFailureStrategy.WARN_AND_TRY
    probe_timeout_ms: int = 60_000

    # Hierarchy
    hierarchy: HierarchyConfig = field(default_factory=HierarchyConfig)
    planner_model: str = ""

    # Auto-split
    auto_split: AutoSplitConfig = field(default_factory=AutoSplitConfig)

    # Completion guard
    completion_guard: CompletionGuardConfig = field(default_factory=CompletionGuardConfig)

    # Model validation
    model_validation: ModelValidationConfig = field(default_factory=ModelValidationConfig)

    # Max verification retries
    max_verification_retries: int = 2

    # Paid only
    paid_only: bool = False

    # Custom task types
    task_types: dict[str, TaskTypeConfig] = field(default_factory=dict)

    # Decomposition
    decomposition_priorities: list[str] | None = None

    # Philosophy
    philosophy: str = ""

    # Communication
    communication: dict[str, Any] = field(default_factory=dict)

    # Permissions
    permissions: dict[str, Any] = field(default_factory=dict)

    # Roles (configurable role overrides — see roles.py)
    roles: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Policy profiles & extensions
    policy_profiles: dict[str, Any] = field(default_factory=dict)
    profile_extensions: dict[str, Any] = field(default_factory=dict)

    # Facts
    facts: dict[str, Any] = field(default_factory=dict)

    # Codebase context (injected at runtime)
    codebase_context: Any = None

    # Resume
    resume_session_id: str | None = None


DEFAULT_SWARM_CONFIG = SwarmConfig()


# =============================================================================
# Retry Context
# =============================================================================


@dataclass
class RetryContext:
    """Context passed to a retried task."""

    previous_feedback: str = ""
    previous_score: int = 0
    attempt: int = 0
    previous_model: str | None = None
    previous_files: list[str] | None = None
    swarm_progress: str | None = None


# =============================================================================
# Partial Context
# =============================================================================


@dataclass
class PartialContext:
    """Context for tasks running with partial dependency data."""

    succeeded: list[str] = field(default_factory=list)  # descriptions
    failed: list[str] = field(default_factory=list)  # descriptions
    ratio: float = 0.0


# =============================================================================
# SwarmTask
# =============================================================================


@dataclass
class SwarmTaskResult:
    """Result of a swarm task execution."""

    success: bool
    output: str
    closure_report: dict[str, Any] | None = None
    quality_score: int | None = None
    quality_feedback: str | None = None
    tokens_used: int = 0
    cost_used: float = 0.0
    duration_ms: int = 0
    files_modified: list[str] | None = None
    findings: list[str] | None = None
    tool_calls: int | None = None
    model: str = ""
    degraded: bool = False
    budget_utilization: dict[str, float] | None = None


@dataclass
class SwarmTask:
    """A single task in the swarm execution."""

    id: str
    description: str
    type: SubtaskType = SubtaskType.IMPLEMENT
    dependencies: list[str] = field(default_factory=list)
    status: SwarmTaskStatus = SwarmTaskStatus.PENDING
    complexity: int = 5  # 1-10
    wave: int = 0
    target_files: list[str] | None = None
    read_files: list[str] | None = None
    assigned_model: str | None = None
    result: SwarmTaskResult | None = None
    attempts: int = 0
    retry_after: float | None = None  # timestamp
    dispatched_at: float | None = None
    dependency_context: str | None = None
    retry_context: RetryContext | None = None
    partial_context: PartialContext | None = None
    is_foundation: bool = False
    tool_count: int | None = None
    tools: list[str] | None = None
    failure_mode: TaskFailureMode | None = None
    pending_cascade_skip: bool = False
    degraded: bool = False
    rescue_context: str | None = None
    parent_task_id: str | None = None
    subtask_ids: list[str] | None = None
    relevant_files: list[str] | None = None
    original_subtask: dict[str, Any] | None = None


@dataclass
class FixupTask(SwarmTask):
    """A fix-up task generated by wave review."""

    fixes_task_id: str = ""
    fix_instructions: str = ""


# =============================================================================
# Swarm Plan
# =============================================================================


@dataclass
class AcceptanceCriterion:
    """Acceptance criterion for a task."""

    task_id: str
    criteria: list[str] = field(default_factory=list)


@dataclass
class IntegrationTestStep:
    """Step in the integration test plan."""

    description: str
    command: str = ""
    expected_result: str = ""
    required: bool = True


@dataclass
class IntegrationTestPlan:
    """Integration test plan."""

    description: str = ""
    steps: list[IntegrationTestStep] = field(default_factory=list)
    success_criteria: str = ""


@dataclass
class SwarmPlan:
    """Execution plan for the swarm."""

    acceptance_criteria: list[AcceptanceCriterion] = field(default_factory=list)
    integration_test_plan: IntegrationTestPlan | None = None
    reasoning: str = ""


# =============================================================================
# Verification
# =============================================================================


@dataclass
class VerificationStepResult:
    """Result of a single verification step."""

    step_index: int
    description: str
    passed: bool
    output: str = ""


@dataclass
class VerificationResult:
    """Result of integration verification."""

    passed: bool
    steps: list[VerificationStepResult] = field(default_factory=list)
    summary: str = ""


# =============================================================================
# Artifact Inventory
# =============================================================================


@dataclass
class ArtifactFile:
    """A file artifact from swarm execution."""

    path: str
    size_bytes: int = 0
    exists: bool = True


@dataclass
class ArtifactInventory:
    """Inventory of all artifacts produced by swarm execution."""

    files: list[ArtifactFile] = field(default_factory=list)
    total_files: int = 0
    total_bytes: int = 0


# =============================================================================
# Stats
# =============================================================================


@dataclass
class SwarmExecutionStats:
    """Statistics from a swarm execution."""

    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    skipped_tasks: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    total_duration_ms: int = 0
    quality_rejections: int = 0
    retries: int = 0
    waves_completed: int = 0
    orchestrator_tokens: int = 0
    orchestrator_cost: float = 0.0


@dataclass
class SwarmExecutionResult:
    """Result of a full swarm execution."""

    success: bool
    summary: str
    stats: SwarmExecutionStats = field(default_factory=SwarmExecutionStats)
    errors: list[dict[str, Any]] = field(default_factory=list)
    plan: SwarmPlan | None = None
    verification: VerificationResult | None = None
    artifact_inventory: ArtifactInventory | None = None
    task_results: dict[str, SwarmTaskResult] = field(default_factory=dict)


# =============================================================================
# Model Health
# =============================================================================


@dataclass
class ModelHealthRecord:
    """Health tracking record for a model."""

    model: str
    successes: int = 0
    failures: int = 0
    rate_limits: int = 0
    last_rate_limit: float | None = None
    average_latency_ms: float = 0.0
    healthy: bool = True
    quality_rejections: int = 0
    success_rate: float = 1.0


# =============================================================================
# Orchestrator Decision
# =============================================================================


@dataclass
class OrchestratorDecision:
    """Record of an orchestrator decision."""

    timestamp: float
    phase: str
    decision: str
    reasoning: str


# =============================================================================
# Swarm Error
# =============================================================================


@dataclass
class SwarmError:
    """Error record from swarm execution."""

    timestamp: float
    phase: str
    message: str
    task_id: str | None = None


# =============================================================================
# Checkpoint
# =============================================================================


@dataclass
class TaskCheckpointState:
    """Serialized task state for checkpoint."""

    id: str
    status: str
    result: dict[str, Any] | None = None
    attempts: int = 0
    wave: int = 0
    assigned_model: str | None = None
    dispatched_at: float | None = None
    description: str = ""
    type: str = ""
    complexity: int = 5
    dependencies: list[str] = field(default_factory=list)
    relevant_files: list[str] | None = None
    is_foundation: bool = False


@dataclass
class SwarmCheckpoint:
    """Full swarm checkpoint for persistence."""

    session_id: str
    timestamp: float
    phase: str
    plan: dict[str, Any] | None = None
    task_states: list[TaskCheckpointState] = field(default_factory=list)
    waves: list[list[str]] = field(default_factory=list)
    current_wave: int = 0
    stats: dict[str, Any] = field(default_factory=dict)
    model_health: list[ModelHealthRecord] = field(default_factory=list)
    decisions: list[OrchestratorDecision] = field(default_factory=list)
    errors: list[SwarmError] = field(default_factory=list)
    original_prompt: str = ""
    shared_context: dict[str, Any] | None = None
    shared_economics: dict[str, Any] | None = None


# =============================================================================
# Swarm Status (for TUI)
# =============================================================================


@dataclass
class SwarmQueueStats:
    """Queue statistics for status display."""

    ready: int = 0
    running: int = 0
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    total: int = 0


@dataclass
class SwarmBudgetStatus:
    """Budget status for display."""

    tokens_used: int = 0
    tokens_total: int = 0
    cost_used: float = 0.0
    cost_total: float = 0.0


@dataclass
class SwarmOrchestratorStatus:
    """Orchestrator-specific status."""

    tokens: int = 0
    cost: float = 0.0
    calls: int = 0


@dataclass
class SwarmWorkerStatus:
    """Live status of an individual swarm worker."""

    task_id: str
    task_description: str
    model: str
    worker_name: str
    elapsed_ms: float = 0.0
    started_at: float = 0.0


@dataclass
class SwarmStatus:
    """Live swarm status snapshot for TUI."""

    phase: SwarmPhase = SwarmPhase.IDLE
    current_wave: int = 0
    total_waves: int = 0
    active_workers: list[SwarmWorkerStatus] = field(default_factory=list)
    queue: SwarmQueueStats = field(default_factory=SwarmQueueStats)
    budget: SwarmBudgetStatus = field(default_factory=SwarmBudgetStatus)
    orchestrator: SwarmOrchestratorStatus = field(default_factory=SwarmOrchestratorStatus)


# =============================================================================
# Spawn Result (from agent spawning)
# =============================================================================


@dataclass
class SpawnResult:
    """Result from spawning an agent."""

    success: bool
    output: str = ""
    tool_calls: int = 0
    files_modified: list[str] | None = None
    closure_report: dict[str, Any] | None = None
    metrics: dict[str, Any] | None = None  # {tokens, duration}
    stderr: str = ""
    session_id: str = ""
    num_turns: int = 0


# =============================================================================
# Wave Review
# =============================================================================


@dataclass
class WaveReviewResult:
    """Result from reviewing a completed wave."""

    assessment: str  # 'good' | 'needs-fixes' | 'critical-issues'
    task_assessments: list[dict[str, Any]] = field(default_factory=list)
    fixup_instructions: list[dict[str, Any]] = field(default_factory=list)


# =============================================================================
# Synthesis
# =============================================================================


@dataclass
class SynthesisResult:
    """Result from synthesizing all task outputs."""

    summary: str = ""
    findings: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


# =============================================================================
# Resource Conflict
# =============================================================================


@dataclass
class ResourceConflict:
    """A file resource conflict between tasks."""

    file_path: str
    task_ids: list[str] = field(default_factory=list)
    conflict_type: str = "write-write"


# =============================================================================
# Decomposition
# =============================================================================


@dataclass
class SmartSubtask:
    """A subtask from LLM decomposition."""

    id: str
    description: str
    type: str = "implement"
    complexity: int = 5
    dependencies: list[str] = field(default_factory=list)
    target_files: list[str] | None = None
    read_files: list[str] | None = None
    relevant_files: list[str] | None = None


@dataclass
class DependencyGraph:
    """Dependency graph from decomposition."""

    parallel_groups: list[list[str]] = field(default_factory=list)
    conflicts: list[ResourceConflict] = field(default_factory=list)


@dataclass
class SmartDecompositionResult:
    """Result from task decomposition."""

    subtasks: list[SmartSubtask] = field(default_factory=list)
    strategy: str = ""
    reasoning: str = ""
    dependency_graph: DependencyGraph = field(default_factory=DependencyGraph)
    llm_assisted: bool = True


# =============================================================================
# Events
# =============================================================================


@dataclass
class SwarmEvent:
    """Base swarm event. The 'type' field discriminates event kinds."""

    type: str
    data: dict[str, Any] = field(default_factory=dict)


# Convenience event constructors
def swarm_event(event_type: str, **kwargs: Any) -> SwarmEvent:
    """Create a swarm event."""
    return SwarmEvent(type=event_type, data=kwargs)


# =============================================================================
# Failure Mode Thresholds
# =============================================================================

FAILURE_MODE_THRESHOLDS: dict[str, float] = {
    "timeout": 0.3,
    "rate-limit": 0.3,
    "error": 0.5,
    "quality": 0.7,
    "hollow": 0.7,
    "cascade": 0.8,
    "recoverable": 0.3,
    "terminal": 1.0,
}


# =============================================================================
# Callback Types
# =============================================================================

from collections.abc import Awaitable, Callable  # noqa: E402

SwarmEventListener = Callable[[SwarmEvent], None]
SpawnAgentFn = Callable[..., Awaitable[SpawnResult]]
