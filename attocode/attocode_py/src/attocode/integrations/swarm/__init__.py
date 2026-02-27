"""Swarm multi-agent orchestration system."""

from attocode.integrations.swarm.config_loader import (
    load_swarm_yaml_config,
    merge_swarm_configs,
    normalize_capabilities,
    normalize_swarm_model_config,
    parse_swarm_yaml,
    yaml_to_swarm_config,
)
from attocode.integrations.swarm.helpers import (
    BOILERPLATE_INDICATORS,
    FAILURE_INDICATORS,
    has_future_intent_language,
    is_hollow_completion,
    repo_looks_unscaffolded,
)
from attocode.integrations.swarm.model_selector import (
    FALLBACK_WORKERS,
    ModelHealthTracker,
    ModelSelectorOptions,
    auto_detect_worker_models,
    get_fallback_workers,
    select_alternative_model,
    select_worker_for_capability,
)
from attocode.integrations.swarm.orchestrator import (
    OrchestratorInternals,
    SwarmOrchestrator,
    create_swarm_orchestrator,
)
from attocode.integrations.swarm.types import (
    DEFAULT_SWARM_CONFIG,
    FAILURE_MODE_THRESHOLDS,
    ArtifactInventory,
    FileConflictStrategy,
    ModelHealthRecord,
    OrchestratorDecision,
    SmartDecompositionResult,
    SmartSubtask,
    SpawnResult,
    SwarmCheckpoint,
    SwarmConfig,
    SwarmError,
    SwarmEvent,
    SwarmEventListener,
    SwarmExecutionResult,
    SwarmExecutionStats,
    SwarmPhase,
    SwarmPlan,
    SwarmQueueStats,
    SwarmStatus,
    SwarmTask,
    SwarmTaskResult,
    SwarmTaskStatus,
    SwarmWorkerSpec,
    SwarmWorkerStatus,
    SubtaskType,
    TaskFailureMode,
    WorkerCapability,
    WorkerRole,
    swarm_event,
)

from attocode.integrations.swarm.request_throttle import (
    FREE_TIER_THROTTLE,
    PAID_TIER_THROTTLE,
    SwarmThrottle,
    ThrottleConfig,
    ThrottleStats,
    ThrottledProvider,
    create_throttled_provider,
)
from attocode.integrations.swarm.swarm_budget import (
    SwarmBudget,
    SwarmBudgetConfig,
    SwarmBudgetStatus,
    WorkerSpending,
)
from attocode.integrations.swarm.failure_classifier import (
    FailureClassification,
    SwarmFailureClass,
    classify_swarm_failure,
)
from attocode.integrations.swarm.swarm_state_store import (
    SwarmStateSnapshot,
    SwarmStateStore,
)
from attocode.integrations.swarm.cc_spawner import (
    create_cc_spawn_fn,
    spawn_cc_worker,
)
from attocode.integrations.swarm.roles import (
    BUILTIN_ROLES,
    RoleConfig,
    build_role_map,
    get_critic_config,
    get_judge_model,
    get_role_config,
    get_scout_config,
)
from attocode.integrations.swarm.critic import (
    build_fixup_tasks,
    review_wave,
)

__all__ = [
    # Types
    "ArtifactInventory",
    "DEFAULT_SWARM_CONFIG",
    "FAILURE_MODE_THRESHOLDS",
    "FileConflictStrategy",
    "ModelHealthRecord",
    "OrchestratorDecision",
    "SmartDecompositionResult",
    "SmartSubtask",
    "SpawnResult",
    "SubtaskType",
    "SwarmCheckpoint",
    "SwarmConfig",
    "SwarmError",
    "SwarmEvent",
    "SwarmEventListener",
    "SwarmExecutionResult",
    "SwarmExecutionStats",
    "SwarmPhase",
    "SwarmPlan",
    "SwarmQueueStats",
    "SwarmStatus",
    "SwarmTask",
    "SwarmTaskResult",
    "SwarmTaskStatus",
    "SwarmWorkerSpec",
    "SwarmWorkerStatus",
    "TaskFailureMode",
    "WorkerCapability",
    "WorkerRole",
    "swarm_event",
    # Orchestrator
    "OrchestratorInternals",
    "SwarmOrchestrator",
    "create_swarm_orchestrator",
    # Helpers
    "BOILERPLATE_INDICATORS",
    "FAILURE_INDICATORS",
    "has_future_intent_language",
    "is_hollow_completion",
    "repo_looks_unscaffolded",
    # Config
    "load_swarm_yaml_config",
    "merge_swarm_configs",
    "normalize_capabilities",
    "normalize_swarm_model_config",
    "parse_swarm_yaml",
    "yaml_to_swarm_config",
    # Model selector
    "FALLBACK_WORKERS",
    "ModelHealthTracker",
    "ModelSelectorOptions",
    "auto_detect_worker_models",
    "get_fallback_workers",
    "select_alternative_model",
    "select_worker_for_capability",
    # request_throttle
    "FREE_TIER_THROTTLE",
    "PAID_TIER_THROTTLE",
    "SwarmThrottle",
    "ThrottleConfig",
    "ThrottleStats",
    "ThrottledProvider",
    "create_throttled_provider",
    # swarm_budget
    "SwarmBudget",
    "SwarmBudgetConfig",
    "SwarmBudgetStatus",
    "WorkerSpending",
    # failure_classifier
    "FailureClassification",
    "SwarmFailureClass",
    "classify_swarm_failure",
    # swarm_state_store
    "SwarmStateSnapshot",
    "SwarmStateStore",
    # cc_spawner
    "create_cc_spawn_fn",
    "spawn_cc_worker",
    # roles
    "BUILTIN_ROLES",
    "RoleConfig",
    "build_role_map",
    "get_critic_config",
    "get_judge_model",
    "get_role_config",
    "get_scout_config",
    # critic
    "build_fixup_tasks",
    "review_wave",
]
