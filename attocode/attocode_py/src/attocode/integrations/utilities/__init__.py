"""Utility integrations."""

from attocode.integrations.utilities.diff_utils import (
    count_changes,
    similarity_ratio,
    unified_diff,
)
from attocode.integrations.utilities.hooks import HookDefinition, HookManager, HookResult
from attocode.integrations.utilities.ignore import IgnoreManager
from attocode.integrations.utilities.logger import get_logger, setup_logging
from attocode.integrations.utilities.mode_manager import AgentMode, ModeManager, ProposedChange
from attocode.integrations.utilities.rules import RulesManager
from attocode.integrations.utilities.token_estimate import count_tokens, estimate_tokens
from attocode.integrations.utilities.resilience import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpenError,
    CircuitState,
    FallbackChain,
    ProviderScore,
    RateLimitConfig,
    RateLimiter,
    RetryConfig,
    Router,
    RoutingStrategy,
    resilient_fetch,
)
from attocode.integrations.utilities.undo import FileChange, FileChangeTracker
from attocode.integrations.utilities.complexity_classifier import (
    Complexity,
    ComplexityAssessment,
    classify_complexity,
)
from attocode.integrations.utilities.execution_policy import (
    ExecutionPolicyManager,
    IntentType,
    PolicyAction,
    PolicyDecision,
    PolicyRule,
)
from attocode.integrations.utilities.thinking_strategy import (
    ThinkingConfig,
    ThinkingMode,
    select_thinking_strategy,
)
from attocode.integrations.utilities.tool_coercion import (
    coerce_boolean,
    coerce_integer,
    coerce_number,
    coerce_string,
    coerce_tool_arguments,
)
from attocode.integrations.utilities.file_change_tracker import (
    ChangeStats,
    ChangeType,
    DetailedFileChangeTracker,
    TrackedChange,
)
from attocode.integrations.utilities.hierarchical_config import (
    ConfigLayer,
    HierarchicalConfigManager,
    ResolvedConfig,
)
from attocode.integrations.utilities.capabilities import (
    Capability,
    ModelCapabilities,
    get_capabilities,
    list_known_models,
)
from attocode.integrations.utilities.thread_manager import (
    ThreadInfo,
    ThreadManager,
    ThreadSnapshot,
)
from attocode.integrations.utilities.memory import (
    MemoryEntry,
    PersistentMemory,
)
from attocode.integrations.utilities.environment_facts import (
    EnvironmentFacts,
    gather_environment_facts,
)

__all__ = [
    # diff_utils
    "count_changes",
    "similarity_ratio",
    "unified_diff",
    # hooks
    "HookDefinition",
    "HookManager",
    "HookResult",
    # ignore
    "IgnoreManager",
    # logger
    "get_logger",
    "setup_logging",
    # mode_manager
    "AgentMode",
    "ModeManager",
    "ProposedChange",
    # rules
    "RulesManager",
    # token_estimate
    "count_tokens",
    "estimate_tokens",
    # resilience
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitBreakerOpenError",
    "CircuitState",
    "FallbackChain",
    "ProviderScore",
    "RateLimitConfig",
    "RateLimiter",
    "RetryConfig",
    "Router",
    "RoutingStrategy",
    "resilient_fetch",
    # undo
    "FileChange",
    "FileChangeTracker",
    # complexity_classifier
    "Complexity",
    "ComplexityAssessment",
    "classify_complexity",
    # execution_policy
    "ExecutionPolicyManager",
    "IntentType",
    "PolicyAction",
    "PolicyDecision",
    "PolicyRule",
    # thinking_strategy
    "ThinkingConfig",
    "ThinkingMode",
    "select_thinking_strategy",
    # tool_coercion
    "coerce_boolean",
    "coerce_integer",
    "coerce_number",
    "coerce_string",
    "coerce_tool_arguments",
    # file_change_tracker
    "ChangeStats",
    "ChangeType",
    "DetailedFileChangeTracker",
    "TrackedChange",
    # hierarchical_config
    "ConfigLayer",
    "HierarchicalConfigManager",
    "ResolvedConfig",
    # capabilities
    "Capability",
    "ModelCapabilities",
    "get_capabilities",
    "list_known_models",
    # thread_manager
    "ThreadInfo",
    "ThreadManager",
    "ThreadSnapshot",
    # memory
    "MemoryEntry",
    "PersistentMemory",
    # environment_facts
    "EnvironmentFacts",
    "gather_environment_facts",
]
