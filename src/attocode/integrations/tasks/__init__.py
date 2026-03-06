"""Task management: DAG, decomposition, planning, verification, work logging."""

from attocode.integrations.tasks.task_manager import TaskManager, TaskNode
from attocode.integrations.tasks.decomposer import (
    ComplexityAssessment,
    ComplexityTier,
    DecomposedTask,
    DecompositionResult,
    classify_complexity,
    decompose_simple,
)
from attocode.integrations.tasks.work_log import WorkEntry, WorkEntryType, WorkLog
from attocode.integrations.tasks.planning import (
    InteractivePlan,
    PlanCheckpoint,
    PlanPhase,
    PlanStep,
    parse_plan_from_markdown,
    plan_to_markdown,
)
from attocode.integrations.tasks.interactive_planning import (
    InteractivePlanner,
    build_draft_prompt,
    build_discuss_prompt,
    build_step_prompt,
)
from attocode.integrations.tasks.pending_plan import (
    PendingPlanManager,
    PendingWrite,
    WriteStatus,
)
from attocode.integrations.tasks.task_splitter import (
    SubTask,
    SubTaskComplexity,
    TaskSplitter,
    build_split_prompt,
    estimate_complexity,
    parse_split_response,
)
from attocode.integrations.tasks.dependency_analyzer import (
    DependencyAnalyzer,
    DependencyGraph,
)
from attocode.integrations.tasks.verification_gate import (
    CheckResult,
    VerificationGate,
    VerificationResult,
    build_verification_prompt,
    check_lint,
    check_tests_pass,
    check_type_errors,
)

__all__ = [
    # task_manager
    "TaskManager",
    "TaskNode",
    # decomposer
    "ComplexityAssessment",
    "ComplexityTier",
    "DecomposedTask",
    "DecompositionResult",
    "classify_complexity",
    "decompose_simple",
    # work_log
    "WorkEntry",
    "WorkEntryType",
    "WorkLog",
    # planning
    "InteractivePlan",
    "PlanCheckpoint",
    "PlanPhase",
    "PlanStep",
    "parse_plan_from_markdown",
    "plan_to_markdown",
    # interactive_planning
    "InteractivePlanner",
    "build_draft_prompt",
    "build_discuss_prompt",
    "build_step_prompt",
    # pending_plan
    "PendingPlanManager",
    "PendingWrite",
    "WriteStatus",
    # task_splitter
    "SubTask",
    "SubTaskComplexity",
    "TaskSplitter",
    "build_split_prompt",
    "estimate_complexity",
    "parse_split_response",
    # dependency_analyzer
    "DependencyAnalyzer",
    "DependencyGraph",
    # verification_gate
    "CheckResult",
    "VerificationGate",
    "VerificationResult",
    "build_verification_prompt",
    "check_lint",
    "check_tests_pass",
    "check_type_errors",
]
