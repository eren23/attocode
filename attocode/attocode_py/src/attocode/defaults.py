"""System defaults and configuration presets.

Ports all presets, resilience configs, policy profiles, and system constants
from the TypeScript defaults.ts. Everything is enabled by default for
educational purposes, but can be disabled for production use.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from attocode.types.budget import (
    BudgetEnforcementMode,
    ExecutionBudget,
)


# =============================================================================
# BUDGET PRESETS
# =============================================================================

QUICK_BUDGET = ExecutionBudget(
    max_tokens=200_000,
    soft_token_limit=160_000,
    max_iterations=20,
)

STANDARD_BUDGET = ExecutionBudget(
    max_tokens=1_000_000,
    soft_token_limit=800_000,
    max_iterations=100,
)

DEEP_BUDGET = ExecutionBudget(
    max_tokens=5_000_000,
    soft_token_limit=4_000_000,
    max_iterations=500,
)

SUBAGENT_BUDGET = ExecutionBudget(
    max_tokens=100_000,
    soft_token_limit=80_000,
    max_iterations=30,
    enforcement_mode=BudgetEnforcementMode.STRICT,
)

LARGE_BUDGET = ExecutionBudget(
    max_tokens=10_000_000,
    soft_token_limit=8_000_000,
    max_iterations=1000,
    enforcement_mode=BudgetEnforcementMode.SOFT,
)

UNLIMITED_BUDGET = ExecutionBudget(
    max_tokens=0,  # 0 = no limit
    soft_token_limit=None,
    max_iterations=None,
    enforcement_mode=BudgetEnforcementMode.ADVISORY,
)

SWARM_WORKER_BUDGET = ExecutionBudget(
    max_tokens=300_000,
    soft_token_limit=240_000,
    max_iterations=50,
    enforcement_mode=BudgetEnforcementMode.STRICT,
)

SWARM_ORCHESTRATOR_BUDGET = ExecutionBudget(
    max_tokens=2_000_000,
    soft_token_limit=1_600_000,
    max_iterations=200,
    enforcement_mode=BudgetEnforcementMode.SOFT,
)

BUDGET_PRESETS: dict[str, ExecutionBudget] = {
    "quick": QUICK_BUDGET,
    "standard": STANDARD_BUDGET,
    "deep": DEEP_BUDGET,
    "subagent": SUBAGENT_BUDGET,
    "large": LARGE_BUDGET,
    "unlimited": UNLIMITED_BUDGET,
    "swarm_worker": SWARM_WORKER_BUDGET,
    "swarm_orchestrator": SWARM_ORCHESTRATOR_BUDGET,
}


# =============================================================================
# ECONOMICS TUNING
# =============================================================================

@dataclass(slots=True)
class EconomicsTuning:
    """Configurable thresholds for economics behavior tuning."""

    doom_loop_threshold: int = 3
    doom_loop_fuzzy_threshold: int = 4
    exploration_file_threshold: int = 10
    exploration_iter_threshold: int = 5
    zero_progress_threshold: int = 5
    progress_checkpoint: int = 5
    max_tool_calls_per_response: int = 25
    circuit_breaker_failure_threshold: int = 5


# =============================================================================
# FEATURE CONFIG DATACLASSES
# =============================================================================

@dataclass(slots=True)
class HooksConfig:
    """Hook system configuration."""

    enabled: bool = True
    logging: bool = False
    metrics: bool = True
    timing: bool = False
    custom: list[Any] = field(default_factory=list)
    shell_enabled: bool = False
    shell_timeout_ms: int = 5000


@dataclass(slots=True)
class RulesConfig:
    """Rules configuration."""

    enabled: bool = True
    sources: list[dict[str, Any]] = field(default_factory=lambda: [
        {"type": "file", "path": "CLAUDE.md", "priority": 1},
        {"type": "file", "path": ".agent/rules.md", "priority": 2},
    ])
    watch: bool = False


@dataclass(slots=True)
class MemoryConfig:
    """Memory configuration."""

    enabled: bool = True
    episodic: bool = True
    semantic: bool = True
    working: bool = True
    retrieval_strategy: str = "hybrid"
    retrieval_limit: int = 10
    persist_path: str | None = None


@dataclass(slots=True)
class PlanningConfig:
    """Planning configuration."""

    enabled: bool = True
    autoplan: bool = True
    complexity_threshold: int = 5
    max_depth: int = 3
    allow_replan: bool = True


@dataclass(slots=True)
class ReflectionConfig:
    """Reflection configuration."""

    enabled: bool = True
    auto_reflect: bool = False
    max_attempts: int = 3
    confidence_threshold: float = 0.8


@dataclass(slots=True)
class ObservabilityConfig:
    """Observability configuration."""

    enabled: bool = True
    tracing_enabled: bool = False
    service_name: str = "production-agent"
    exporter: str = "console"
    collect_tokens: bool = True
    collect_costs: bool = True
    collect_latencies: bool = True
    logging_enabled: bool = False
    log_level: str = "info"
    structured: bool = True


@dataclass(slots=True)
class RoutingConfig:
    """Provider routing configuration."""

    enabled: bool = False
    models: list[str] = field(default_factory=list)
    strategy: str = "balanced"
    rules: list[Any] = field(default_factory=list)
    fallback_chain: list[str] = field(default_factory=list)
    circuit_breaker: bool = True


@dataclass(slots=True)
class SandboxConfig:
    """Sandbox configuration."""

    enabled: bool = True
    isolation: str = "process"
    mode: str = "auto"
    allowed_commands: list[str] = field(default_factory=lambda: [
        # JS/TS toolchain
        "node", "npm", "npx", "yarn", "pnpm", "bun", "tsc",
        "eslint", "prettier", "jest", "vitest", "mocha",
        # Python toolchain
        "python", "python3", "pip", "pip3", "uv", "ruff",
        "mypy", "pytest", "black", "isort",
        # Git
        "git",
        # File inspection
        "ls", "cat", "head", "tail", "grep", "find", "wc",
        "echo", "pwd", "which", "env",
        # File manipulation
        "mkdir", "cp", "mv", "touch", "rm", "rmdir", "chmod", "ln",
        # Text processing
        "sed", "awk", "sort", "tr", "cut", "uniq", "diff", "xargs",
        # Path utilities
        "basename", "dirname", "realpath", "readlink",
        # Archive / compression
        "tar", "gzip", "gunzip", "zip", "unzip",
        # System info
        "date", "uname",
        # Other languages & tools
        "curl", "wget", "make", "jq", "docker", "docker-compose",
        "cargo", "go", "java", "mvn", "gradle",
    ])
    blocked_commands: list[str] = field(default_factory=lambda: [
        "rm -rf /", "rm -rf ~", "sudo", "chmod 777",
        "curl | sh", "curl | bash", "wget | sh", "wget | bash",
    ])
    max_cpu_seconds: int = 30
    max_memory_mb: int = 512
    max_output_bytes: int = 1_048_576  # 1MB
    timeout: int = 60_000
    network_allowed: bool = False
    docker_image: str = "python:3.12-slim"


@dataclass(slots=True)
class HumanInLoopConfig:
    """Human-in-the-loop configuration."""

    enabled: bool = True
    risk_threshold: str = "high"
    always_approve: list[str] = field(default_factory=lambda: [
        "delete_file", "rm", "drop_table", "truncate",
    ])
    never_approve: list[str] = field(default_factory=lambda: [
        "read_file", "list_directory", "search",
        "task_create", "task_update", "task_get", "task_list",
    ])
    approval_timeout: int = 300_000
    audit_log: bool = True


@dataclass(slots=True)
class MultiAgentConfig:
    """Multi-agent configuration."""

    enabled: bool = False
    roles: list[Any] = field(default_factory=list)
    consensus_strategy: str = "voting"
    communication_mode: str = "broadcast"
    coordinator_role: str | None = None


@dataclass(slots=True)
class ExecutionPolicyConfig:
    """Execution policy configuration."""

    enabled: bool = True
    default_policy: str = "prompt"
    tool_policies: dict[str, dict[str, str]] = field(default_factory=lambda: {
        "read_file": {"policy": "allow"},
        "list_directory": {"policy": "allow"},
        "search": {"policy": "allow"},
        "task_create": {"policy": "allow"},
        "task_update": {"policy": "allow"},
        "task_get": {"policy": "allow"},
        "task_list": {"policy": "allow"},
    })
    intent_aware: bool = True
    intent_confidence_threshold: float = 0.7
    preset: str = "balanced"


@dataclass(slots=True)
class PolicyEngineConfig:
    """Unified policy engine configuration."""

    enabled: bool = True
    legacy_fallback: bool = True
    default_profile: str = "code-full"
    default_swarm_profile: str = "code-strict-bash"
    profiles: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ThreadsConfig:
    """Threads (checkpoint/rollback) configuration."""

    enabled: bool = True
    auto_checkpoint: bool = True
    checkpoint_frequency: int = 5
    max_checkpoints: int = 10
    enable_rollback: bool = True
    enable_forking: bool = True


@dataclass(slots=True)
class CancellationConfig:
    """Cancellation configuration."""

    enabled: bool = True
    default_timeout: int = 0
    grace_period: int = 5_000


@dataclass(slots=True)
class ResourceConfig:
    """Resource monitoring configuration."""

    enabled: bool = True
    max_memory_mb: int = 512
    max_cpu_time_sec: int = 1_800  # 30 minutes per-prompt
    max_concurrent_ops: int = 10
    warn_threshold: float = 0.7
    critical_threshold: float = 0.9


@dataclass(slots=True)
class LSPConfig:
    """Language Server Protocol configuration."""

    enabled: bool = False
    auto_detect: bool = True
    servers: list[Any] | None = None
    timeout: int = 30_000


@dataclass(slots=True)
class SemanticCacheConfig:
    """Semantic cache configuration."""

    enabled: bool = False
    threshold: float = 0.95
    max_size: int = 1_000
    ttl: int = 0


@dataclass(slots=True)
class SkillsConfig:
    """Skills configuration."""

    enabled: bool = True
    directories: list[str] | None = None
    load_built_in: bool = True
    auto_activate: bool = False


@dataclass(slots=True)
class CodebaseContextConfig:
    """Codebase context configuration."""

    enabled: bool = True
    include_patterns: list[str] = field(default_factory=lambda: [
        "**/*.ts", "**/*.tsx", "**/*.js", "**/*.jsx",
        "**/*.py", "**/*.go", "**/*.rs",
    ])
    exclude_patterns: list[str] = field(default_factory=lambda: [
        "**/node_modules/**", "**/dist/**", "**/build/**",
        "**/.git/**", "**/__pycache__/**", "**/.venv/**",
    ])
    max_file_size: int = 102_400  # 100KB
    max_tokens: int = 50_000
    strategy: str = "importance_first"


@dataclass(slots=True)
class CompactionConfig:
    """Compaction configuration."""

    enabled: bool = True
    token_threshold: int = 160_000
    preserve_recent_count: int = 10
    preserve_tool_results: bool = True
    summary_max_tokens: int = 2_000
    summary_model: str | None = None
    mode: str = "auto"


@dataclass(slots=True)
class InteractivePlanningConfig:
    """Interactive planning configuration."""

    enabled: bool = False
    enable_checkpoints: bool = True
    auto_checkpoint_interval: int = 3
    max_plan_steps: int = 20
    require_approval: bool = True


@dataclass(slots=True)
class RecursiveContextConfig:
    """Recursive context (RLM) configuration."""

    enabled: bool = False
    max_recursion_depth: int = 5
    max_snippet_tokens: int = 2_000
    cache_navigation_results: bool = True
    enable_synthesis: bool = True


@dataclass(slots=True)
class LearningStoreConfig:
    """Learning store configuration."""

    enabled: bool = True
    db_path: str | None = None
    require_validation: bool = True
    auto_validate_threshold: float = 0.9
    max_learnings: int = 500


@dataclass(slots=True)
class LLMResilienceConfig:
    """LLM resilience configuration."""

    enabled: bool = True
    max_empty_retries: int = 2
    max_continuations: int = 3
    auto_continue: bool = True
    min_content_length: int = 1
    incomplete_action_recovery: bool = True
    max_incomplete_action_retries: int = 2
    enforce_requested_artifacts: bool = True
    incomplete_action_auto_loop: bool = True
    max_incomplete_auto_loops: int = 2
    auto_loop_prompt_style: str = "strict"
    task_lease_stale_ms: int = 300_000  # 5 minutes


@dataclass(slots=True)
class FileChangeTrackerConfig:
    """File change tracker configuration."""

    enabled: bool = False
    max_full_content_bytes: int = 51_200  # 50KB


@dataclass(slots=True)
class SubagentConfig:
    """Subagent configuration."""

    enabled: bool = True
    default_timeout: int = 900_000  # 15 minutes
    default_max_iterations: int = 15
    inherit_observability: bool = True
    wrapup_window_ms: int = 30_000
    idle_check_interval_ms: int = 5_000


@dataclass(slots=True)
class ProviderResilienceConfig:
    """Provider resilience configuration."""

    enabled: bool = True
    failure_threshold: int = 5
    reset_timeout: int = 30_000
    half_open_requests: int = 1
    trip_on_errors: list[str] = field(default_factory=lambda: [
        "RATE_LIMITED", "SERVER_ERROR", "NETWORK_ERROR", "TIMEOUT",
    ])
    fallback_providers: list[str] = field(default_factory=list)
    cooldown_ms: int = 60_000
    fallback_failure_threshold: int = 3


# =============================================================================
# SUBAGENT TIMEOUTS & ITERATION LIMITS
# =============================================================================

SUBAGENT_TIMEOUTS: dict[str, int] = {
    "researcher": 1_200_000,  # 20 minutes
    "coder": 900_000,         # 15 minutes
    "reviewer": 600_000,      # 10 minutes
    "architect": 1_200_000,   # 20 minutes
    "debugger": 900_000,      # 15 minutes
    "documenter": 600_000,    # 10 minutes
    "default": 900_000,       # 15 minutes fallback
}

SUBAGENT_MAX_ITERATIONS: dict[str, int] = {
    "researcher": 50,
    "coder": 40,
    "reviewer": 25,
    "architect": 40,
    "debugger": 40,
    "documenter": 20,
    "default": 30,
}

TIMEOUT_EXTENSION_ON_PROGRESS = 120_000  # +2 minutes when making progress


def get_subagent_timeout(agent_type: str) -> int:
    """Get timeout for a specific agent type."""
    return SUBAGENT_TIMEOUTS.get(agent_type, SUBAGENT_TIMEOUTS["default"])


def get_subagent_max_iterations(agent_type: str) -> int:
    """Get max iterations for a specific agent type."""
    return SUBAGENT_MAX_ITERATIONS.get(agent_type, SUBAGENT_MAX_ITERATIONS["default"])


# =============================================================================
# DEFAULT FEATURE CONFIGS
# =============================================================================

DEFAULT_HOOKS_CONFIG = HooksConfig()
DEFAULT_RULES_CONFIG = RulesConfig()
DEFAULT_MEMORY_CONFIG = MemoryConfig()
DEFAULT_PLANNING_CONFIG = PlanningConfig()
DEFAULT_REFLECTION_CONFIG = ReflectionConfig()
DEFAULT_OBSERVABILITY_CONFIG = ObservabilityConfig()
DEFAULT_ROUTING_CONFIG = RoutingConfig()
DEFAULT_SANDBOX_CONFIG = SandboxConfig()
DEFAULT_HUMAN_IN_LOOP_CONFIG = HumanInLoopConfig()
DEFAULT_MULTI_AGENT_CONFIG = MultiAgentConfig()
DEFAULT_EXECUTION_POLICY_CONFIG = ExecutionPolicyConfig()
DEFAULT_POLICY_ENGINE_CONFIG = PolicyEngineConfig()
DEFAULT_THREADS_CONFIG = ThreadsConfig()
DEFAULT_CANCELLATION_CONFIG = CancellationConfig()
DEFAULT_RESOURCE_CONFIG = ResourceConfig()
DEFAULT_LSP_CONFIG = LSPConfig()
DEFAULT_SEMANTIC_CACHE_CONFIG = SemanticCacheConfig()
DEFAULT_SKILLS_CONFIG = SkillsConfig()
DEFAULT_CODEBASE_CONTEXT_CONFIG = CodebaseContextConfig()
DEFAULT_COMPACTION_CONFIG = CompactionConfig()
DEFAULT_INTERACTIVE_PLANNING_CONFIG = InteractivePlanningConfig()
DEFAULT_RECURSIVE_CONTEXT_CONFIG = RecursiveContextConfig()
DEFAULT_LEARNING_STORE_CONFIG = LearningStoreConfig()
DEFAULT_LLM_RESILIENCE_CONFIG = LLMResilienceConfig()
DEFAULT_FILE_CHANGE_TRACKER_CONFIG = FileChangeTrackerConfig()
DEFAULT_SUBAGENT_CONFIG = SubagentConfig()
DEFAULT_PROVIDER_RESILIENCE_CONFIG = ProviderResilienceConfig()
DEFAULT_ECONOMICS_TUNING = EconomicsTuning()


# =============================================================================
# MERGE HELPERS
# =============================================================================

def merge_config(defaults: Any, user_config: Any | None) -> Any:
    """Merge user config with defaults.

    User values override defaults; False disables the feature.
    """
    if user_config is False:
        return False
    if user_config is None:
        return defaults
    if not hasattr(defaults, "__dataclass_fields__"):
        return user_config

    merged = type(defaults)(**{
        f.name: getattr(user_config, f.name, None) or getattr(defaults, f.name)
        for f in defaults.__dataclass_fields__.values()
    })
    return merged


def is_feature_enabled(config: Any) -> bool:
    """Check if a feature is enabled in config."""
    if config is False or config is None:
        return False
    if hasattr(config, "enabled"):
        return config.enabled is not False
    return True


# =============================================================================
# DEFAULT SYSTEM PROMPT
# =============================================================================

DEFAULT_SYSTEM_PROMPT = """You are Attocode, a production coding agent with full access to the filesystem and development tools.

## Your Capabilities

**File Operations:**
- read_file: Read file contents
- write_file: Create or overwrite files
- edit_file: Make targeted edits to existing files
- list_files: List directory contents
- glob: Find files by pattern (e.g., "**/*.ts")
- grep: Search file contents with regex

**Command Execution:**
- bash: Run shell commands (git, npm, make, etc.)

**Code Intelligence:**
- codebase_overview: Get pre-analyzed AST data — file structure, symbols, signatures.
  Use for broad exploration BEFORE resorting to glob/read_file.
- Built-in subagents: researcher, coder, reviewer, architect, debugger, documenter
- You can spawn subagents for specialized tasks
- MCP servers may provide additional tools (check with mcp_tool_search)

**Context Management:**
- Memory system retains information across conversation
- Checkpoints allow rollback to previous states
- Context compaction prevents overflow on long sessions

## Tool Rules (CRITICAL)
- **Creating files:** ALWAYS use write_file. NEVER use bash with cat/heredoc/echo for file creation.
- **Editing files:** ALWAYS use edit_file. NEVER use bash with sed/awk for file editing.
- **Reading files:** ALWAYS use read_file. NEVER use bash with cat/head/tail.
- **Finding files:** ALWAYS use glob. NEVER use bash with find/ls.
- **Searching code:** ALWAYS use grep. NEVER use bash with grep/rg.
- **bash is ONLY for:** running commands (npm, git, make, tsc, tests, docker, etc.)

## Exploration Strategy

Use a two-tier approach:

**Broad exploration** (default for questions like "what does this codebase do?" or \
"show me all services"):
1. First, read the **Relevant Code (Pre-Analyzed AST Data)** section already in your \
context — it contains file structure and exported symbols from static analysis.
2. If you need a filtered, refreshed, or more detailed view, call **codebase_overview** \
with appropriate mode/directory/symbolType filters.
3. No glob or read_file needed for broad understanding.

**Targeted exploration** (for specific function bodies, string searches, or edits):
1. Use **grep** to find specific patterns across the codebase.
2. Use **read_file** on specific files identified from the repo map or grep results.
3. Use **glob** when searching for files by name pattern.

## Guidelines

1. **Use your tools** - You have real filesystem access. Read files, run commands, make changes.
2. **Batch operations** - Call multiple tools in parallel when they're independent.
3. **Verify changes** - After editing, read the file back or run tests to confirm.
4. **Be direct** - You can actually do things, not just explain how. Do them.
5. **Ask if unclear** - Request clarification for ambiguous tasks.
"""
