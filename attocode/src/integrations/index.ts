/**
 * Lesson 25: Integration Module Exports
 *
 * Clean re-exports of all integration modules.
 */

// Core integrations (Lessons 10-22)
export { HookManager, createHookManager } from './hooks.js';
export { MemoryManager, createMemoryManager } from './memory.js';
export { PlanningManager, createPlanningManager, type ReflectionResult } from './planning.js';
export {
  Tracer,
  MetricsCollector,
  Logger,
  ObservabilityManager,
  createObservabilityManager,
} from './observability.js';
export {
  SandboxManager,
  HumanInLoopManager,
  SafetyManager,
  createSafetyManager,
} from './safety.js';
export { RoutingManager, createRoutingManager } from './routing.js';

// Rules system (from Lesson 12)
export {
  RulesManager,
  createRulesManager,
  parseRulesFromMarkdown,
  DEFAULT_RULE_SOURCES,
  type RuleSource,
  type RulesConfig,
  type LoadedRule,
  type RulesEvent,
  type RulesEventListener,
} from './rules.js';

// Economics system (token budgets, progress detection)
export {
  ExecutionEconomicsManager,
  createEconomicsManager,
  QUICK_BUDGET,
  STANDARD_BUDGET,
  LARGE_BUDGET,
  UNLIMITED_BUDGET,
  type ExecutionBudget,
  type ExecutionUsage,
  type BudgetCheckResult,
  type ExtensionRequest,
  type EconomicsEvent,
  type EconomicsEventListener,
} from './economics.js';

// Extensible agent registry
export {
  AgentRegistry,
  createAgentRegistry,
  filterToolsForAgent,
  formatAgentList,
  type AgentDefinition,
  type LoadedAgent,
  type SpawnOptions,
  type SpawnResult,
  type RegistryEvent,
  type RegistryEventListener,
} from './agent-registry.js';

// Multi-agent coordination (from Lesson 17)
export {
  MultiAgentManager,
  createMultiAgentManager,
  CODER_ROLE,
  REVIEWER_ROLE,
  ARCHITECT_ROLE,
  RESEARCHER_ROLE,
  type AgentRole,
  type TeamConfig,
  type TeamTask,
  type TeamResult,
  type ConsensusStrategy,
  type MultiAgentEvent,
  type MultiAgentEventListener,
} from './multi-agent.js';

// ReAct pattern (from Lesson 18)
export {
  ReActManager,
  createReActManager,
  extractThoughts,
  extractActions,
  hasCoherentReasoning,
  type ReActConfig,
  type ReActStep,
  type ReActAction,
  type ReActTrace,
  type ReActEvent,
  type ReActEventListener,
} from './react.js';

// Execution policies (from Lesson 23)
export {
  ExecutionPolicyManager,
  createExecutionPolicyManager,
  STRICT_POLICY,
  BALANCED_POLICY,
  PERMISSIVE_POLICY,
  type PolicyLevel,
  type IntentType,
  type ExecutionPolicyConfig,
  type PolicyEvaluation,
  type PermissionGrant,
  type IntentClassification,
  type PolicyEvent,
  type PolicyEventListener,
} from './execution-policy.js';

// Thread management (from Lesson 24)
export {
  ThreadManager,
  createThreadManager,
  createWithHistory,
  exportThread,
  getThreadLineage,
  type Thread,
  type Checkpoint,
  type CheckpointState,
  type MergeStrategy,
  type ThreadEvent,
  type ThreadEventListener,
} from './thread-manager.js';

// Session persistence
export {
  SessionStore,
  createSessionStore,
  formatSessionList,
  type SessionMetadata,
  type SessionEntry,
  type SessionStoreConfig,
  type SessionEvent,
  type SessionEventListener,
} from './session-store.js';

// SQLite session persistence (preferred for production)
export {
  SQLiteStore,
  createSQLiteStore,
  type SQLiteStoreConfig,
  type Goal,
  type GoalStatus,
  type Juncture,
  type JunctureType,
  type WorkerResult,
  type WorkerResultStatus,
  type WorkerResultRef,
  type SessionManifest,
} from './sqlite-store.js';

// Schema management (embedded migrations)
export {
  MIGRATIONS,
  applyMigrations as applySchemaMigrations,
  getMigrationStatus as getSchemaMigrationStatus,
  needsMigration as schemaNeedsMigration,
  detectFeatures,
  type Migration,
  type MigrationResult,
  type SchemaFeatures,
} from '../persistence/schema.js';

// Streaming responses
export {
  StreamHandler,
  createStreamHandler,
  formatChunkForTerminal,
  adaptOpenRouterStream,
  adaptAnthropicStream,
  type StreamChunk,
  type StreamCallback,
  type StreamConfig,
  type StreamEvent,
  type StreamEventListener,
} from './streaming.js';

// Context compaction
export {
  Compactor,
  createCompactor,
  formatCompactionResult,
  getContextUsage,
  getContextBreakdown,
  formatContextBreakdown,
  type CompactionConfig,
  type CompactionResult,
  type CompactionEvent,
  type CompactionEventListener,
  type ContextBreakdown,
  type ToolDefinition,
} from './compaction.js';

// MCP client
export {
  MCPClient,
  createMCPClient,
  formatServerList,
  getSampleMCPConfig,
  type MCPServerConfig,
  type MCPConfigFile,
  type MCPClientConfig,
  type MCPServerInfo,
  type MCPEvent,
  type MCPEventListener,
  type MCPToolSummary,
  type MCPContextStats,
} from './mcp-client.js';

// MCP tool search (dynamic tool discovery)
export {
  createMCPToolSearchTool,
  createMCPToolListTool,
  createMCPContextStatsTool,
  createMCPMetaTools,
  formatToolSummaries,
  formatContextStats,
  type MCPToolSearchResult,
  type MCPToolSearchOptions,
} from './mcp-tool-search.js';

// Cancellation tokens
export {
  CancellationManager,
  createCancellationManager,
  createCancellationTokenSource,
  createTimeoutToken,
  createLinkedToken,
  withCancellation,
  sleep,
  race,
  toAbortSignal,
  isCancellationError,
  CancellationError,
  CancellationToken,
  type CancellationToken as CancellationTokenType,
  type CancellationTokenSource,
  type CancellableOptions,
  type CancellationEvent,
  type CancellationEventListener,
} from './cancellation.js';

// Resource monitoring
export {
  ResourceManager,
  createResourceManager,
  createStrictResourceManager,
  createLenientResourceManager,
  combinedShouldContinue,
  isResourceLimitError,
  ResourceLimitError,
  type ResourceLimitsConfig,
  type ResourceUsage,
  type ResourceStatus,
  type ResourceCheck,
  type ResourceEvent,
  type ResourceEventListener,
} from './resources.js';

// Hierarchical configuration
export {
  HierarchicalConfigManager,
  createHierarchicalConfig,
  createAndLoadConfig,
  getSampleGlobalConfig,
  getSampleWorkspaceConfig,
  ensureConfigDirectories,
  type ConfigLevel,
  type LevelConfig,
  type ResolvedConfig,
  type ConfigEvent,
  type ConfigEventListener,
  type HierarchicalConfigOptions,
} from './hierarchical-config.js';

// LSP (Language Server Protocol)
export {
  LSPManager,
  createLSPManager,
  createAndStartLSPManager,
  type LSPConfig,
  type LanguageServerConfig,
  type LSPPosition,
  type LSPRange,
  type LSPLocation,
  type LSPDiagnostic,
  type LSPCompletion,
  type DiagnosticSeverity,
  type CompletionKind,
  type LSPEvent,
  type LSPEventListener,
} from './lsp.js';

// Semantic Cache
export {
  SemanticCacheManager,
  createSemanticCacheManager,
  createStrictCache,
  createLenientCache,
  withSemanticCache,
  cosineSimilarity,
  type SemanticCacheConfig,
  type CacheEntry,
  type CacheHit,
  type CacheStats,
  type EmbeddingFunction,
  type CacheEvent,
  type CacheEventListener,
} from './semantic-cache.js';

// OS-Specific Sandbox (renamed to avoid conflict with SandboxManager from safety.js)
export {
  SandboxManager as OSSandboxManager,
  createSandboxManager as createOSSandboxManager,
  createSandbox,
  sandboxExec,
  SeatbeltSandbox,
  DockerSandbox,
  BasicSandbox,
  type Sandbox,
  type ExecResult,
  type SandboxOptions,
  type SandboxMode,
  type SandboxManagerConfig as OSSandboxManagerConfig,
  type SandboxEvent as OSSandboxEvent,
  type SandboxEventListener as OSSandboxEventListener,
} from './sandbox/index.js';

// Skills Standard
export {
  SkillManager,
  createSkillManager,
  formatSkillList,
  getSampleSkillContent,
  getDefaultSkillDirectories,
  type Skill,
  type SkillTrigger,
  type SkillsConfig,
  type SkillEvent,
  type SkillEventListener,
} from './skills.js';

// Ignore File Support
export {
  IgnoreManager,
  createIgnoreManager,
  quickShouldIgnore,
  getSampleAgentignore,
  getBuiltinIgnorePatterns,
  type IgnorePattern,
  type IgnoreConfig,
  type IgnoreEvent,
  type IgnoreEventListener,
} from './ignore.js';

// Persistent PTY Shell
export {
  PTYShellManager,
  createPTYShell,
  createAndStartPTYShell,
  createPTYShellTool,
  formatShellState,
  type PTYShellConfig,
  type CommandResult,
  type ShellState,
  type PTYEvent,
  type PTYEventListener,
} from './pty-shell.js';

// Context Engineering (Manus-inspired tricks P, Q, R, S, T)
export {
  ContextEngineeringManager,
  createContextEngineering,
  createMinimalContextEngineering,
  createFullContextEngineering,
  stableStringify,
  calculateOptimalFrequency,
  createReconstructionPrompt,
  extractInsights,
  type ContextEngineeringConfig,
  type ContextMessage,
  type ContextEngineeringStats,
  type ContextEngineeringEvent,
  type ContextEngineeringEventListener,
} from './context-engineering.js';

// Codebase Context (intelligent code selection)
export {
  CodebaseContextManager,
  createCodebaseContext,
  buildContextFromChunks,
  summarizeRepoStructure,
  type CodeChunk,
  type MinimalCodeChunk,
  type CodeChunkType,
  type RepoMap,
  type CodebaseContextConfig,
  type SelectionOptions,
  type SelectionStrategy,
  type SelectionResult,
  type CodebaseContextEvent,
  type CodebaseContextEventListener,
} from './codebase-context.js';

// Shared Blackboard (subagent coordination)
export {
  SharedBlackboard,
  createSharedBlackboard,
  createFindingFromOutput,
  extractFindings,
  type Finding,
  type FindingType,
  type ResourceClaim,
  type ClaimType,
  type Subscription,
  type FindingFilter,
  type BlackboardConfig,
  type BlackboardEvent,
  type BlackboardEventListener,
  type BlackboardStats,
} from './shared-blackboard.js';

// Smart Decomposer (semantic task decomposition)
export {
  SmartDecomposer,
  createSmartDecomposer,
  createDecompositionPrompt,
  parseDecompositionResponse,
  type SmartSubtask,
  type SubtaskStatus,
  type SubtaskType,
  type DependencyGraph,
  type ResourceConflict,
  type SmartDecompositionResult,
  type DecompositionStrategy,
  type SmartDecomposerConfig,
  type LLMDecomposeFunction,
  type DecomposeContext,
  type LLMDecomposeResult,
  type SmartDecomposerEvent,
  type SmartDecomposerEventListener,
} from './smart-decomposer.js';

// Result Synthesizer (structured result merging)
export {
  ResultSynthesizer,
  createResultSynthesizer,
  createSynthesisPrompt,
  type AgentOutput,
  type OutputType,
  type FileChange,
  type Hunk,
  type ResultConflict,
  type ConflictType,
  type ConflictResolution,
  type ResolutionStrategy,
  type SynthesisResult,
  type SynthesisStats,
  type SynthesisMethod,
  type ResultSynthesizerConfig,
  type LLMSynthesizeFunction,
  type LLMSynthesisResult,
  type ResultSynthesizerEvent,
  type ResultSynthesizerEventListener,
} from './result-synthesizer.js';

// Pending Plan (plan mode write interception)
export {
  PendingPlanManager,
  createPendingPlanManager,
  formatPlanStatus,
  type PendingPlan,
  type ProposedChange,
  type PlanStatus,
  type PlanApprovalResult,
  type PendingPlanEvent,
  type PendingPlanEventListener,
} from './pending-plan.js';
