/**
 * Lesson 25: Default Configurations
 *
 * Sensible defaults for all features. Everything is enabled by default
 * for educational purposes, but can be disabled for production use.
 */

import type {
  HooksConfig,
  PluginsConfig,
  RulesConfig,
  MemoryConfig,
  PlanningConfig,
  ReflectionConfig,
  ObservabilityConfig,
  RoutingConfig,
  SandboxConfig,
  HumanInLoopConfig,
  MultiAgentConfig,
  ReActPatternConfig,
  ExecutionPolicyConfig,
  ThreadsConfig,
  CancellationConfig,
  ResourceConfig,
  LSPAgentConfig,
  SemanticCacheAgentConfig,
  SkillsAgentConfig,
  CodebaseContextAgentConfig,
  CompactionAgentConfig,
  InteractivePlanningAgentConfig,
  RecursiveContextAgentConfig,
  LearningStoreAgentConfig,
  LLMResilienceAgentConfig,
  FileChangeTrackerAgentConfig,
  SubagentConfig,
  ProviderResilienceConfig,
  ProductionAgentConfig,
} from './types.js';

// =============================================================================
// FEATURE DEFAULTS
// =============================================================================

/**
 * Default hooks configuration.
 * Console output is DISABLED by default - enable explicitly when needed.
 */
export const DEFAULT_HOOKS_CONFIG: HooksConfig = {
  enabled: true,
  builtIn: {
    logging: false, // Disabled by default - prints [Hook] logs to console
    metrics: true,
    timing: false,  // Disabled by default - prints [Hook] timing to console
  },
  custom: [],
};

/**
 * Default plugins configuration.
 */
export const DEFAULT_PLUGINS_CONFIG: PluginsConfig = {
  enabled: true,
  plugins: [],
  discoveryPaths: [],
};

/**
 * Default rules configuration.
 */
export const DEFAULT_RULES_CONFIG: RulesConfig = {
  enabled: true,
  sources: [
    { type: 'file', path: 'CLAUDE.md', priority: 1 },
    { type: 'file', path: '.agent/rules.md', priority: 2 },
  ],
  watch: false,
};

/**
 * Default memory configuration.
 */
export const DEFAULT_MEMORY_CONFIG: MemoryConfig = {
  enabled: true,
  types: {
    episodic: true,
    semantic: true,
    working: true,
  },
  retrievalStrategy: 'hybrid',
  retrievalLimit: 10,
  persistPath: undefined, // In-memory by default
};

/**
 * Default planning configuration.
 */
export const DEFAULT_PLANNING_CONFIG: PlanningConfig = {
  enabled: true,
  autoplan: true,
  complexityThreshold: 5,
  maxDepth: 3,
  allowReplan: true,
};

/**
 * Default reflection configuration.
 */
export const DEFAULT_REFLECTION_CONFIG: ReflectionConfig = {
  enabled: true,
  autoReflect: false, // Manual reflection by default
  maxAttempts: 3,
  confidenceThreshold: 0.8,
};

/**
 * Default observability configuration.
 * Console output is DISABLED by default - enable explicitly when needed.
 */
export const DEFAULT_OBSERVABILITY_CONFIG: ObservabilityConfig = {
  enabled: true,
  tracing: {
    enabled: false, // Disabled by default - prints trace tree to console
    serviceName: 'production-agent',
    exporter: 'console',
  },
  metrics: {
    enabled: true,
    collectTokens: true,
    collectCosts: true,
    collectLatencies: true,
  },
  logging: {
    enabled: false, // Disabled by default - prints JSON logs to console
    level: 'info',
    structured: true,
  },
};

/**
 * Default routing configuration.
 */
export const DEFAULT_ROUTING_CONFIG: RoutingConfig = {
  enabled: false, // Disabled by default (requires multiple providers)
  models: [],
  strategy: 'balanced',
  rules: [],
  fallbackChain: [],
  circuitBreaker: true,
};

/**
 * Default sandbox configuration.
 */
export const DEFAULT_SANDBOX_CONFIG: SandboxConfig = {
  enabled: true,
  isolation: 'process',
  mode: 'auto', // Auto-detect best sandbox (seatbelt on macOS, docker on Linux, basic fallback)
  allowedCommands: [
    'node', 'npm', 'npx', 'yarn', 'pnpm', 'bun',
    'git', 'ls', 'cat', 'head', 'tail', 'grep', 'find', 'wc',
    'echo', 'pwd', 'which', 'env', 'mkdir', 'cp', 'mv', 'touch',
    'tsc', 'eslint', 'prettier', 'jest', 'vitest', 'mocha',
  ],
  blockedCommands: [
    'rm -rf /',
    'rm -rf ~',
    'sudo',
    'chmod 777',
    'curl | sh',
    'curl | bash',
    'wget | sh',
    'wget | bash',
  ],
  resourceLimits: {
    maxCpuSeconds: 30,
    maxMemoryMB: 512,
    maxOutputBytes: 1024 * 1024, // 1MB
    timeout: 60000, // 1 minute
  },
  allowedPaths: ['.', process.cwd()],
  readablePaths: ['/'],
  networkAllowed: false, // Network disabled by default for security
  dockerImage: 'node:20-slim', // Default Docker image
};

/**
 * Default human-in-the-loop configuration.
 */
export const DEFAULT_HUMAN_IN_LOOP_CONFIG: HumanInLoopConfig = {
  enabled: true,
  riskThreshold: 'high', // Only require approval for high-risk actions
  alwaysApprove: [
    'delete_file',
    'rm',
    'drop_table',
    'truncate',
  ],
  neverApprove: [
    'read_file',
    'list_directory',
    'search',
  ],
  approvalTimeout: 300000, // 5 minutes
  approvalHandler: undefined, // Will use default console prompt
  auditLog: true,
};

/**
 * Default multi-agent configuration.
 */
export const DEFAULT_MULTI_AGENT_CONFIG: MultiAgentConfig = {
  enabled: false, // Disabled by default (requires explicit role setup)
  roles: [],
  consensusStrategy: 'voting',
  communicationMode: 'broadcast',
  coordinatorRole: undefined,
};

/**
 * Default ReAct pattern configuration.
 */
export const DEFAULT_REACT_CONFIG: ReActPatternConfig = {
  enabled: false, // Disabled by default (use runWithReAct() explicitly)
  maxSteps: 15,
  stopOnAnswer: true,
  includeReasoning: true,
};

/**
 * Default execution policy configuration.
 */
export const DEFAULT_EXECUTION_POLICY_CONFIG: ExecutionPolicyConfig = {
  enabled: true, // Enabled by default for safety
  defaultPolicy: 'prompt',
  toolPolicies: {
    read_file: { policy: 'allow' },
    list_directory: { policy: 'allow' },
    search: { policy: 'allow' },
  },
  intentAware: true,
  intentConfidenceThreshold: 0.7,
  preset: 'balanced',
};

/**
 * Default threads configuration.
 */
export const DEFAULT_THREADS_CONFIG: ThreadsConfig = {
  enabled: true, // Enabled by default for safety and recovery
  autoCheckpoint: true,
  checkpointFrequency: 5, // Every 5 iterations
  maxCheckpoints: 10,
  enableRollback: true,
  enableForking: true,
};

/**
 * Default cancellation configuration.
 */
export const DEFAULT_CANCELLATION_CONFIG: CancellationConfig = {
  enabled: true, // Enabled by default for graceful interruption
  defaultTimeout: 0, // No timeout by default (controlled by maxIterations)
  gracePeriod: 5000, // 5 seconds for cleanup after cancellation
};

/**
 * Default resource monitoring configuration.
 * Note: CPU time is reset per-prompt, so this limit applies to a single prompt's execution,
 * not the entire session. 30 minutes allows complex multi-subagent tasks to complete.
 */
export const DEFAULT_RESOURCE_CONFIG: ResourceConfig = {
  enabled: true, // Enabled by default for resource protection
  maxMemoryMB: 512, // 512MB default memory limit
  maxCpuTimeSec: 1800, // 30 minutes per-prompt CPU time limit (reset on each new prompt)
  maxConcurrentOps: 10, // Max 10 concurrent operations
  warnThreshold: 0.7, // Warn at 70% usage
  criticalThreshold: 0.9, // Critical at 90% usage
};

/**
 * Default LSP (Language Server Protocol) configuration.
 */
export const DEFAULT_LSP_CONFIG: LSPAgentConfig = {
  enabled: false, // Disabled by default (requires language servers to be installed)
  autoDetect: true, // Auto-detect languages when enabled
  servers: undefined, // Use built-in server configs
  timeout: 30000, // 30 second timeout for LSP requests
};

/**
 * Default semantic cache configuration.
 */
export const DEFAULT_SEMANTIC_CACHE_CONFIG: SemanticCacheAgentConfig = {
  enabled: false, // Disabled by default (optimization, not critical)
  threshold: 0.95, // High similarity threshold for cache hits
  maxSize: 1000, // Max 1000 cached entries
  ttl: 0, // No expiry by default
};

/**
 * Default skills configuration.
 */
export const DEFAULT_SKILLS_CONFIG: SkillsAgentConfig = {
  enabled: true, // Enabled by default for discoverable capabilities
  directories: undefined, // Uses getDefaultSkillDirectories() from skills.ts
  loadBuiltIn: true, // Load built-in skills
  autoActivate: false, // Manual activation by default
};

/**
 * Default compaction configuration.
 *
 * Note: The actual compaction threshold is calculated as 80% of the model's
 * context window (from ModelRegistry). The tokenThreshold here is a fallback
 * for when the model's context window is unknown.
 */
export const DEFAULT_COMPACTION_CONFIG: CompactionAgentConfig = {
  enabled: true, // Enabled by default for context management
  tokenThreshold: 160000, // Fallback: 80% of 200K (Claude's default context)
  preserveRecentCount: 10, // Keep last 10 messages verbatim
  preserveToolResults: true, // Keep tool results
  summaryMaxTokens: 2000, // Summary size limit
  summaryModel: undefined, // Uses default model
  mode: 'auto', // Auto-compact without prompting
};

// =============================================================================
// MERGE HELPERS
// =============================================================================

/**
 * Merge user config with defaults.
 * User values override defaults; false disables the feature.
 */
export function mergeConfig<T extends object>(
  defaults: T,
  userConfig: Partial<T> | false | undefined
): T | false {
  if (userConfig === false) {
    return false;
  }

  if (userConfig === undefined) {
    return defaults;
  }

  return {
    ...defaults,
    ...userConfig,
    // Deep merge nested objects
    ...Object.fromEntries(
      Object.entries(userConfig).map(([key, value]) => {
        const defaultValue = defaults[key as keyof T];
        if (
          typeof value === 'object' &&
          value !== null &&
          !Array.isArray(value) &&
          typeof defaultValue === 'object' &&
          defaultValue !== null &&
          !Array.isArray(defaultValue)
        ) {
          return [key, { ...defaultValue, ...value }];
        }
        return [key, value];
      })
    ),
  } as T;
}

/**
 * Default codebase context configuration.
 */
export const DEFAULT_CODEBASE_CONTEXT_CONFIG: CodebaseContextAgentConfig = {
  enabled: false, // Disabled by default (optimization, not critical)
  includePatterns: ['**/*.ts', '**/*.tsx', '**/*.js', '**/*.jsx', '**/*.py', '**/*.go', '**/*.rs'],
  excludePatterns: ['**/node_modules/**', '**/dist/**', '**/build/**', '**/.git/**'],
  maxFileSize: 100 * 1024, // 100KB
  maxTokens: 50000,
  strategy: 'importance_first',
};

/**
 * Default interactive planning configuration.
 */
export const DEFAULT_INTERACTIVE_PLANNING_CONFIG: InteractivePlanningAgentConfig = {
  enabled: false, // Disabled by default (feature in development)
  enableCheckpoints: true,
  autoCheckpointInterval: 3,
  maxPlanSteps: 20,
  requireApproval: true,
};

/**
 * Default recursive context (RLM) configuration.
 */
export const DEFAULT_RECURSIVE_CONTEXT_CONFIG: RecursiveContextAgentConfig = {
  enabled: false, // Disabled by default (feature in development)
  maxRecursionDepth: 5,
  maxSnippetTokens: 2000,
  cacheNavigationResults: true,
  enableSynthesis: true,
};

/**
 * Default learning store configuration.
 * Cross-session learning from failures.
 */
export const DEFAULT_LEARNING_STORE_CONFIG: LearningStoreAgentConfig = {
  enabled: true, // Enabled by default for cross-session learning
  dbPath: undefined, // Uses default .agent/learnings.db
  requireValidation: true, // Require user validation for safety
  autoValidateThreshold: 0.9, // High confidence threshold
  maxLearnings: 500,
};

/**
 * Default LLM resilience configuration.
 * Handles empty responses and max_tokens continuation.
 */
export const DEFAULT_LLM_RESILIENCE_CONFIG: LLMResilienceAgentConfig = {
  enabled: true, // Enabled by default for reliability
  maxEmptyRetries: 2,
  maxContinuations: 3,
  autoContinue: true,
  minContentLength: 1,
  incompleteActionRecovery: true,
  maxIncompleteActionRetries: 2,
  enforceRequestedArtifacts: true,
};

/**
 * Default file change tracker configuration.
 * Enables undo capability for file operations.
 */
export const DEFAULT_FILE_CHANGE_TRACKER_CONFIG: FileChangeTrackerAgentConfig = {
  enabled: false, // Disabled by default (requires database setup)
  maxFullContentBytes: 50 * 1024, // 50KB
};

/**
 * Agent-type-specific timeout configurations.
 * Research tasks need more time than focused review tasks.
 *
 * NOTE: Timeouts were increased to better support research-heavy workflows.
 * The previous defaults (2-5 min) caused frequent timeouts during exploration.
 */
export const SUBAGENT_TIMEOUTS: Record<string, number> = {
  researcher: 420000,    // 7 minutes - exploration needs time (was 5 min)
  coder: 300000,         // 5 minutes - implementation tasks (was 3 min)
  reviewer: 180000,      // 3 minutes - focused review (was 2 min)
  architect: 360000,     // 6 minutes - design thinking (was 4 min)
  debugger: 300000,      // 5 minutes - investigation (was 3 min)
  documenter: 180000,    // 3 minutes - documentation (was 2 min)
  default: 300000,       // 5 minutes - fallback (was 2 min)
} as const;

/**
 * Agent-type-specific iteration limits.
 * Research may need more iterations than documentation.
 */
export const SUBAGENT_MAX_ITERATIONS: Record<string, number> = {
  researcher: 25,        // More iterations for thorough exploration
  coder: 20,             // Sufficient for implementation
  reviewer: 15,          // Focused review needs fewer
  architect: 20,         // Design requires iteration
  debugger: 20,          // Investigation can be iterative
  documenter: 10,        // Documentation is straightforward
  default: 15,           // Balanced default
} as const;

/**
 * Extension granted when subagent shows progress.
 * If tool calls are happening, grant more time.
 */
export const TIMEOUT_EXTENSION_ON_PROGRESS = 60000; // +1 minute when making progress

/**
 * Get timeout for a specific agent type.
 */
export function getSubagentTimeout(agentType: string): number {
  return SUBAGENT_TIMEOUTS[agentType] ?? SUBAGENT_TIMEOUTS.default;
}

/**
 * Get max iterations for a specific agent type.
 */
export function getSubagentMaxIterations(agentType: string): number {
  return SUBAGENT_MAX_ITERATIONS[agentType] ?? SUBAGENT_MAX_ITERATIONS.default;
}

/**
 * Default subagent configuration.
 * Controls timeout and iteration limits for spawned subagents.
 *
 * NOTE: Research-focused tasks often need more time than 2 minutes.
 * The default timeout was increased from 120s to 300s (5 minutes) to allow
 * subagents to complete research tasks without premature timeout.
 */
export const DEFAULT_SUBAGENT_CONFIG: SubagentConfig = {
  enabled: true, // Enabled by default
  defaultTimeout: 300000, // 5 minutes per subagent (increased from 2 min for research tasks)
  defaultMaxIterations: 15, // Balanced default (agent-specific limits preferred)
  inheritObservability: true,
  wrapupWindowMs: 30000, // 30s graceful wrapup before hard timeout kill
  idleCheckIntervalMs: 5000, // Check idle timeout every 5s
};

/**
 * Default provider resilience configuration.
 * Controls circuit breaker and fallback chain for LLM provider calls.
 */
export const DEFAULT_PROVIDER_RESILIENCE_CONFIG: ProviderResilienceConfig = {
  enabled: true, // Enabled by default for production reliability
  circuitBreaker: {
    failureThreshold: 5,
    resetTimeout: 30000, // 30 seconds
    halfOpenRequests: 1,
    tripOnErrors: ['RATE_LIMITED', 'SERVER_ERROR', 'NETWORK_ERROR', 'TIMEOUT'],
  },
  fallbackProviders: [], // No fallback by default (single provider)
  fallbackChain: {
    cooldownMs: 60000, // 1 minute cooldown
    failureThreshold: 3,
  },
};

/**
 * Build complete configuration from partial user config.
 */
export function buildConfig(
  userConfig: Partial<ProductionAgentConfig>
): Required<Omit<ProductionAgentConfig, 'provider' | 'tools' | 'toolResolver' | 'mcpToolSummaries' | 'maxContextTokens' | 'blackboard' | 'fileCache' | 'budget'>> & Pick<ProductionAgentConfig, 'provider' | 'tools' | 'toolResolver' | 'mcpToolSummaries' | 'maxContextTokens' | 'blackboard' | 'fileCache' | 'budget'> {
  return {
    provider: userConfig.provider!,
    tools: userConfig.tools || [],
    systemPrompt: userConfig.systemPrompt || DEFAULT_SYSTEM_PROMPT,
    model: userConfig.model || 'default',
    maxTokens: userConfig.maxTokens ?? 4096,
    temperature: userConfig.temperature ?? 0.7,
    hooks: mergeConfig(DEFAULT_HOOKS_CONFIG, userConfig.hooks),
    plugins: mergeConfig(DEFAULT_PLUGINS_CONFIG, userConfig.plugins),
    rules: mergeConfig(DEFAULT_RULES_CONFIG, userConfig.rules),
    memory: mergeConfig(DEFAULT_MEMORY_CONFIG, userConfig.memory),
    planning: mergeConfig(DEFAULT_PLANNING_CONFIG, userConfig.planning),
    reflection: mergeConfig(DEFAULT_REFLECTION_CONFIG, userConfig.reflection),
    observability: mergeConfig(DEFAULT_OBSERVABILITY_CONFIG, userConfig.observability),
    routing: mergeConfig(DEFAULT_ROUTING_CONFIG, userConfig.routing),
    sandbox: mergeConfig(DEFAULT_SANDBOX_CONFIG, userConfig.sandbox),
    humanInLoop: mergeConfig(DEFAULT_HUMAN_IN_LOOP_CONFIG, userConfig.humanInLoop),
    multiAgent: mergeConfig(DEFAULT_MULTI_AGENT_CONFIG, userConfig.multiAgent),
    react: mergeConfig(DEFAULT_REACT_CONFIG, userConfig.react),
    executionPolicy: mergeConfig(DEFAULT_EXECUTION_POLICY_CONFIG, userConfig.executionPolicy),
    threads: mergeConfig(DEFAULT_THREADS_CONFIG, userConfig.threads),
    cancellation: mergeConfig(DEFAULT_CANCELLATION_CONFIG, userConfig.cancellation),
    resources: mergeConfig(DEFAULT_RESOURCE_CONFIG, userConfig.resources),
    lsp: mergeConfig(DEFAULT_LSP_CONFIG, userConfig.lsp),
    semanticCache: mergeConfig(DEFAULT_SEMANTIC_CACHE_CONFIG, userConfig.semanticCache),
    skills: mergeConfig(DEFAULT_SKILLS_CONFIG, userConfig.skills),
    codebaseContext: mergeConfig(DEFAULT_CODEBASE_CONTEXT_CONFIG, userConfig.codebaseContext),
    interactivePlanning: mergeConfig(DEFAULT_INTERACTIVE_PLANNING_CONFIG, userConfig.interactivePlanning),
    recursiveContext: mergeConfig(DEFAULT_RECURSIVE_CONTEXT_CONFIG, userConfig.recursiveContext),
    compaction: mergeConfig(DEFAULT_COMPACTION_CONFIG, userConfig.compaction),
    learningStore: mergeConfig(DEFAULT_LEARNING_STORE_CONFIG, userConfig.learningStore),
    resilience: mergeConfig(DEFAULT_LLM_RESILIENCE_CONFIG, userConfig.resilience),
    fileChangeTracker: mergeConfig(DEFAULT_FILE_CHANGE_TRACKER_CONFIG, userConfig.fileChangeTracker),
    subagent: mergeConfig(DEFAULT_SUBAGENT_CONFIG, userConfig.subagent),
    swarm: userConfig.swarm || false,
    providerResilience: mergeConfig(DEFAULT_PROVIDER_RESILIENCE_CONFIG, userConfig.providerResilience),
    maxContextTokens: userConfig.maxContextTokens, // Dynamic: fetched from OpenRouter/ModelRegistry if not explicitly set
    maxIterations: userConfig.maxIterations ?? 50,
    timeout: userConfig.timeout ?? 300000, // 5 minutes
    toolResolver: userConfig.toolResolver, // Optional: for lazy-loading MCP tools
    mcpToolSummaries: userConfig.mcpToolSummaries, // Optional: MCP tool summaries for system prompt
    budget: userConfig.budget, // Optional: custom budget for subagents
  };
}

// =============================================================================
// DEFAULT SYSTEM PROMPT
// =============================================================================

export const DEFAULT_SYSTEM_PROMPT = `You are Attocode, a production coding agent with full access to the filesystem and development tools.

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
- Built-in subagents: researcher, coder, reviewer, architect, debugger, documenter
- You can spawn subagents for specialized tasks
- MCP servers may provide additional tools (check with mcp_tool_search)

**Context Management:**
- Memory system retains information across conversation
- Checkpoints allow rollback to previous states
- Context compaction prevents overflow on long sessions

## Guidelines

1. **Use your tools** - You have real filesystem access. Read files, run commands, make changes.
2. **Batch operations** - Call multiple tools in parallel when they're independent.
3. **Verify changes** - After editing, read the file back or run tests to confirm.
4. **Be direct** - You can actually do things, not just explain how. Do them.
5. **Ask if unclear** - Request clarification for ambiguous tasks.

## Tool Usage Pattern

When exploring a codebase:
\`\`\`
1. glob("**/*.ts") to find TypeScript files
2. read_file on key files (package.json, README, main entry)
3. grep for specific patterns
\`\`\`

When making changes:
\`\`\`
1. read_file to understand current state
2. edit_file to make changes
3. bash("npm run typecheck") to verify
\`\`\``;

// =============================================================================
// FEATURE DETECTION
// =============================================================================

/**
 * Check if a feature is enabled in config.
 */
export function isFeatureEnabled<T extends { enabled?: boolean }>(
  config: T | false | undefined
): config is T {
  if (config === false || config === undefined) {
    return false;
  }
  return config.enabled !== false;
}

/**
 * Get enabled features from config.
 */
export function getEnabledFeatures(config: ReturnType<typeof buildConfig>): string[] {
  const features: string[] = [];

  if (isFeatureEnabled(config.hooks)) features.push('hooks');
  if (isFeatureEnabled(config.plugins)) features.push('plugins');
  if (isFeatureEnabled(config.rules)) features.push('rules');
  if (isFeatureEnabled(config.memory)) features.push('memory');
  if (isFeatureEnabled(config.planning)) features.push('planning');
  if (isFeatureEnabled(config.reflection)) features.push('reflection');
  if (isFeatureEnabled(config.observability)) features.push('observability');
  if (isFeatureEnabled(config.routing)) features.push('routing');
  if (isFeatureEnabled(config.sandbox)) features.push('sandbox');
  if (isFeatureEnabled(config.humanInLoop)) features.push('humanInLoop');
  if (isFeatureEnabled(config.multiAgent)) features.push('multiAgent');
  if (isFeatureEnabled(config.react)) features.push('react');
  if (isFeatureEnabled(config.executionPolicy)) features.push('executionPolicy');
  if (isFeatureEnabled(config.threads)) features.push('threads');
  if (isFeatureEnabled(config.cancellation)) features.push('cancellation');
  if (isFeatureEnabled(config.resources)) features.push('resources');
  if (isFeatureEnabled(config.lsp)) features.push('lsp');
  if (isFeatureEnabled(config.semanticCache)) features.push('semanticCache');
  if (isFeatureEnabled(config.skills)) features.push('skills');

  return features;
}
