/**
 * Lesson 25: Integration Module Exports
 *
 * Clean re-exports of all integration modules.
 */

// Core integrations (Lessons 10-22)
export { HookManager, createHookManager } from './utilities/hooks.js';
export { MemoryManager, createMemoryManager } from './utilities/memory.js';
export { PlanningManager, createPlanningManager, type ReflectionResult } from './tasks/planning.js';
export {
  Tracer,
  MetricsCollector,
  Logger,
  ObservabilityManager,
  createObservabilityManager,
} from './utilities/observability.js';
export {
  SandboxManager,
  HumanInLoopManager,
  SafetyManager,
  createSafetyManager,
  type ApprovalScope,
} from './safety/safety.js';
export { RoutingManager, createRoutingManager } from './utilities/routing.js';
export {
  DEFAULT_POLICY_PROFILES,
  DEFAULT_POLICY_ENGINE_CONFIG,
  resolvePolicyProfile,
  isToolAllowedByProfile,
  evaluateBashCommandByProfile,
  mergeApprovalScopeWithProfile,
  type ResolvePolicyProfileOptions,
  type ResolvedPolicyProfile,
} from './safety/policy-engine.js';
export {
  detectFileMutationViaBash,
  evaluateBashPolicy,
  isReadOnlyBashCommand,
  isWriteLikeBashCommand,
  type BashMode,
  type BashWriteProtection,
  type BashPolicyDecision,
} from './safety/bash-policy.js';

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
} from './utilities/rules.js';

// Economics system (token budgets, progress detection)
export {
  ExecutionEconomicsManager,
  createEconomicsManager,
  computeToolFingerprint,
  QUICK_BUDGET,
  STANDARD_BUDGET,
  SUBAGENT_BUDGET,
  LARGE_BUDGET,
  UNLIMITED_BUDGET,
  SWARM_WORKER_BUDGET,
  SWARM_ORCHESTRATOR_BUDGET,
  TIMEOUT_WRAPUP_PROMPT,
  type ExecutionBudget,
  type ExecutionUsage,
  type BudgetCheckResult,
  type ExtensionRequest,
  type EconomicsEvent,
  type EconomicsEventListener,
  type LoopDetectionState,
  type PhaseBudgetConfig,
} from './budget/economics.js';

// Loop Detector (extracted from economics - doom loop + pattern detection)
export {
  LoopDetector,
  extractBashResult,
  extractBashFileTarget,
  type RecentToolCall,
} from './budget/loop-detector.js';

// Phase Tracker (extracted from economics - phase transitions + nudges)
export { PhaseTracker } from './budget/phase-tracker.js';

// Work Log (compaction-resilient summary)
export {
  WorkLog,
  createWorkLog,
  type WorkLogEntry,
  type TestResult as WorkLogTestResult,
  type ApproachEntry,
  type WorkLogConfig,
} from './tasks/work-log.js';

// Verification Gate (opt-in completion verification)
export {
  VerificationGate,
  createVerificationGate,
  type VerificationCriteria,
  type VerificationState,
  type VerificationCheckResult,
} from './tasks/verification-gate.js';

// Extensible agent registry
export {
  AgentRegistry,
  createAgentRegistry,
  filterToolsForAgent,
  formatAgentList,
  getDefaultAgentDirectories,
  getAgentCreationDirectory,
  getUserAgentDirectory,
  getAgentSourceType,
  getAgentLocationDisplay,
  getAgentScaffold,
  createAgentScaffold,
  getAgentStats,
  type AgentDefinition,
  type LoadedAgent,
  type AgentSourceType,
  type SpawnOptions,
  type SpawnResult,
  type StructuredClosureReport,
  type RegistryEvent,
  type RegistryEventListener,
  type AgentScaffoldResult,
} from './agents/agent-registry.js';

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
} from './agents/multi-agent.js';

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
} from './utilities/react.js';

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
} from './safety/execution-policy.js';

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
} from './utilities/thread-manager.js';

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
} from './persistence/session-store.js';

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
} from './persistence/sqlite-store.js';

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
} from './streaming/streaming.js';

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
} from './context/compaction.js';

// Auto-Compaction Manager
export {
  AutoCompactionManager,
  createAutoCompactionManager,
  formatCompactionCheckResult,
  getSuggestedAction,
  type AutoCompactionConfig,
  type CompactionCheckResult,
  type AutoCompactionEvent,
  type AutoCompactionEventListener,
} from './context/auto-compaction.js';

// File Change Tracker (undo capability)
export {
  FileChangeTracker,
  createFileChangeTracker,
  type FileChangeTrackerConfig,
  type FileChange as TrackedFileChange,
  type UndoResult,
  type ChangeSummary,
} from './utilities/file-change-tracker.js';

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
} from './mcp/mcp-client.js';

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
} from './mcp/mcp-tool-search.js';

// Cancellation tokens
export {
  CancellationManager,
  createCancellationManager,
  createCancellationTokenSource,
  createTimeoutToken,
  createLinkedToken,
  createProgressAwareTimeout,
  createGracefulTimeout,
  withCancellation,
  sleep,
  race,
  toAbortSignal,
  isCancellationError,
  CancellationError,
  CancellationToken,
  type CancellationToken as CancellationTokenType,
  type CancellationTokenSource,
  type ProgressAwareTimeoutSource,
  type GracefulTimeoutSource,
  type CancellableOptions,
  type CancellationEvent,
  type CancellationEventListener,
} from './budget/cancellation.js';

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
} from './budget/resources.js';

/**
 * Hierarchical configuration.
 * @deprecated Use `loadConfig()` from `../config/index.js` instead.
 * This module is unused and will be removed in a future release.
 */
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
} from './utilities/hierarchical-config.js';

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
} from './lsp/lsp.js';

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
} from './context/semantic-cache.js';

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
} from './safety/sandbox/index.js';

// Skills Standard
export {
  SkillManager,
  createSkillManager,
  formatSkillList,
  getSampleSkillContent,
  getDefaultSkillDirectories,
  getSkillCreationDirectory,
  getUserSkillDirectory,
  getSkillSourceType,
  getSkillLocationDisplay,
  getSkillScaffold,
  createSkillScaffold,
  getSkillStats,
  type Skill,
  type SkillArgument,
  type SkillTrigger,
  type SkillSourceType,
  type SkillsConfig,
  type SkillEvent,
  type SkillEventListener,
  type SkillScaffoldResult,
} from './skills/skills.js';

// Skill Executor (invokable skills)
export {
  SkillExecutor,
  createSkillExecutor,
  type ParsedArgs,
  type SkillExecutionContext,
  type SkillExecutionResult,
  type SkillExecutorEvent,
  type SkillExecutorEventListener,
} from './skills/skill-executor.js';

// Capabilities Registry (unified discovery)
export {
  CapabilitiesRegistry,
  createCapabilitiesRegistry,
  formatCapabilitiesSummary,
  formatCapabilitiesList,
  formatSearchResults,
  type Capability,
  type CapabilityType,
  type CapabilitySearchResult,
  type CapabilityCounts,
  type CapabilitiesEvent,
  type CapabilitiesEventListener,
} from './utilities/capabilities.js';

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
} from './utilities/ignore.js';

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
} from './streaming/pty-shell.js';

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
  type CacheableContentBlock,
} from './context/context-engineering.js';

// Codebase Context (intelligent code selection)
export {
  CodebaseContextManager,
  createCodebaseContext,
  buildContextFromChunks,
  generateLightweightRepoMap,
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
  // Enhanced search (Phase 4.4)
  type SearchOptions,
  type RankedSearchOptions,
  type ScoredChunk,
} from './context/codebase-context.js';

// AST Cache Stats + Incremental Reparse
export {
  getASTCacheStats,
  computeTreeEdit,
  diffSymbols,
  diffDependencies,
  type ASTSymbol,
  type ASTParameter,
  type ASTDecorator,
  type ASTDependency,
  type SymbolChange,
  type FileChangeResult,
} from './context/codebase-ast.js';

// Edit Validator (Phase 5.1)
export {
  validateSyntax,
  validateEdit,
  type ValidationResult,
  type SyntaxError,
} from './safety/edit-validator.js';

// TypeScript compilation checker
export {
  detectTypeScriptProject,
  runTypeCheck,
  parseTypeCheckOutput,
  formatTypeCheckNudge,
  createTypeCheckerState,
  type TypeCheckError,
  type TypeCheckResult,
  type TypeCheckerState,
} from './safety/type-checker.js';

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
} from './agents/shared-blackboard.js';

// Shared Budget Pool (parent-child token budget sharing)
export {
  SharedBudgetPool,
  createBudgetPool,
  type BudgetPoolConfig,
  type BudgetAllocation,
  type BudgetPoolStats,
} from './budget/budget-pool.js';

// Shared File Cache (cross-agent read deduplication)
export {
  SharedFileCache,
  createSharedFileCache,
  type FileCacheConfig,
  type FileCacheStats,
  type FileCacheEntry,
} from './context/file-cache.js';

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
} from './tasks/smart-decomposer.js';

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
} from './agents/result-synthesizer.js';

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
} from './tasks/pending-plan.js';

// Persistence utilities (debug logging, checkpoint management)
export {
  PersistenceDebugger,
  persistenceDebug,
  saveCheckpointToStore,
  loadSessionState,
  type AnySessionStore,
  type CheckpointData,
} from './persistence/persistence.js';

// Interactive Planning (conversational + editable planning)
export {
  InteractivePlanner,
  createInteractivePlanner,
  formatPlan,
  formatStep,
  type InteractivePlan,
  type PlanStep,
  type PlanCheckpoint,
  type PlanStatus as InteractivePlanStatus,
  type EditCommand,
  type ParsedEdit,
  type PlannerLLMCall,
  type InteractivePlannerConfig,
  type InteractivePlannerEvent,
  type InteractivePlannerEventListener,
} from './tasks/interactive-planning.js';

// Learning Store (persistent cross-session learning)
export {
  LearningStore,
  createLearningStore,
  createInMemoryLearningStore,
  formatLearningsContext,
  formatLearningStats,
  type Learning,
  type LearningProposal,
  type LearningStatus,
  type LearningType,
  type LearningStoreConfig,
  type LearningStoreEvent,
  type LearningStoreEventListener,
} from './quality/learning-store.js';

// Recursive Context (RLM) - from tricks
export {
  RecursiveContextManager,
  createRecursiveContext,
  createMinimalRecursiveContext,
  createFileSystemSource,
  createConversationSource,
  formatRecursiveResult,
  formatRecursiveStats,
  type ContextSource,
  type NavigationCommand,
  type RecursiveResult,
  type NavigationStep,
  type RecursiveStats,
  type RecursiveContextConfig,
  type ProcessOptions as RecursiveProcessOptions,
  type LLMCallFunction,
  type RecursiveContextEvent,
  type RecursiveContextEventListener,
} from '../tricks/recursive-context.js';

// Provider Resilience (circuit breaker + fallback chain)
export {
  getResilientProvider,
  createResilientFallbackChain,
  createAutoFallbackChain,
  getCircuitBreaker,
  getAllCircuitBreakerMetrics,
  resetAllCircuitBreakers,
  formatResilienceStatus,
  hasResilientProviderSupport,
  type ResilientProviderConfig,
  type ResilientChainConfig,
} from '../providers/resilient-provider.js';

// Circuit Breaker (for direct use)
export {
  CircuitBreaker,
  createCircuitBreaker,
  createStrictCircuitBreaker,
  createLenientCircuitBreaker,
  formatCircuitBreakerMetrics,
  isCircuitBreakerError,
  type CircuitState,
  type CircuitBreakerConfig,
  type CircuitBreakerMetrics,
  type CircuitBreakerEvent,
  type CircuitBreakerEventListener,
} from '../providers/circuit-breaker.js';

// Fallback Chain (for direct use)
export {
  FallbackChain,
  createFallbackChain,
  createFallbackChainFromRegistry,
  formatHealthStatus,
  isChainExhaustedError,
  type ChainedProvider,
  type ProviderHealth,
  type FallbackChainConfig,
  type FallbackChainEvent,
  type FallbackChainEventListener,
} from '../providers/fallback-chain.js';

// Retry utility for transient failures
export {
  withRetry,
  withRetryResult,
  TOOL_RETRY_CONFIG,
  MCP_RETRY_CONFIG,
  FILE_RETRY_CONFIG,
  NETWORK_RETRY_CONFIG,
  DEFAULT_RETRYABLE_ERRORS,
  DEFAULT_RETRYABLE_CODES,
  type RetryConfig,
  type RetryResult,
} from './utilities/retry.js';

// Centralized error types (CancellationError exported from cancellation.js above)
export {
  ErrorCategory,
  AgentError,
  ToolError,
  MCPError,
  FileOperationError,
  ProviderError,
  ValidationError,
  CancellationError as AgentCancellationError, // Alias to avoid conflict with cancellation.ts
  ResourceError,
  categorizeError,
  wrapError,
  isAgentError,
  isRecoverable,
  isTransient,
  isRateLimited,
  formatError,
  formatErrorForLog,
} from '../errors/index.js';

// Health check system
export {
  HealthChecker,
  createHealthChecker,
  createProviderHealthCheck,
  createFileSystemHealthCheck,
  createSQLiteHealthCheck,
  createMCPHealthCheck,
  createNetworkHealthCheck,
  formatHealthReport,
  healthReportToJSON,
  type HealthCheckResult,
  type HealthReport,
  type HealthCheckFn,
  type HealthCheckConfig,
  type HealthCheckerConfig,
  type HealthEvent,
  type HealthEventListener,
} from './quality/health-check.js';

// Dead letter queue for failed operations
export {
  DeadLetterQueue,
  createDeadLetterQueue,
  formatDeadLetterStats,
  type DeadLetterItem,
  type DeadLetterStatus,
  type AddDeadLetterInput,
  type DeadLetterQueryOptions,
  type DeadLetterStats,
  type DeadLetterEvent,
  type DeadLetterEventListener,
} from './quality/dead-letter-queue.js';

// Graph Visualization (dependency diagrams)
export {
  generateDependencyDiagram,
  generateFocusedDiagram,
  generateReverseDiagram,
  createGraphVisualizer,
  type FileDependencyGraph,
  type DiagramFormat,
  type DiagramDirection,
  type GraphVisualizationOptions,
  type DiagramResult,
} from './utilities/graph-visualization.js';

// Task Management (Claude Code-style)
export {
  TaskManager,
  createTaskManager,
  type Task,
  type TaskStatus,
  type CreateTaskOptions,
  type UpdateTaskOptions,
  type TaskSummary,
} from './tasks/task-manager.js';

// Command History (persistent input history)
export {
  HistoryManager,
  createHistoryManager,
  type HistoryManagerConfig,
} from './persistence/history.js';

// Swarm Mode (orchestrator + worker models)
export {
  SwarmOrchestrator,
  createSwarmOrchestrator,
  SwarmThrottle,
  ThrottledProvider,
  createThrottledProvider,
  FREE_TIER_THROTTLE,
  PAID_TIER_THROTTLE,
  SwarmTaskQueue,
  createSwarmTaskQueue,
  SwarmWorkerPool,
  createSwarmWorkerPool,
  createSwarmBudgetPool,
  autoDetectWorkerModels,
  selectWorkerForCapability,
  evaluateWorkerOutput,
  isSwarmEvent,
  formatSwarmEvent,
  DEFAULT_SWARM_CONFIG,
  subtaskToSwarmTask,
  taskResultToAgentOutput,
  SUBTASK_TO_CAPABILITY,
  type SwarmConfig,
  type SwarmWorkerSpec,
  type WorkerCapability,
  type WorkerRole,
  type SwarmTask,
  type SwarmTaskStatus,
  type SwarmTaskResult,
  type SwarmExecutionResult,
  type SwarmExecutionStats,
  type SwarmError,
  type SwarmStatus,
  type SwarmWorkerStatus,
  type SwarmEvent,
  type SwarmEventListener,
  type SwarmBudgetPool,
  type SpawnAgentFn,
  type ModelSelectorOptions,
  type QualityGateResult,
  type ThrottleConfig,
  type ThrottleStats,
} from './swarm/index.js';

// Delegation Protocol (structured subagent delegation)
export {
  buildDelegationPrompt,
  createMinimalDelegationSpec,
  DELEGATION_INSTRUCTIONS,
  type DelegationSpec,
  type OutputFormatSpec,
  type ToolGuidance,
  type TaskBoundaries,
  type SiblingContext,
} from './agents/delegation-protocol.js';

// Complexity Classifier (task complexity heuristics)
export {
  classifyComplexity,
  getScalingGuidance,
  createComplexityClassifier,
  type ComplexityTier,
  type ComplexityAssessment,
  type ExecutionRecommendation,
  type ComplexitySignal,
  type ClassificationContext,
} from './agents/complexity-classifier.js';

// Tool Recommendation Engine (task-type to tool mapping)
export {
  ToolRecommendationEngine,
  createToolRecommendationEngine,
  type ToolRecommendation,
  type ToolRecommendationConfig,
  type ToolCategory,
} from './quality/tool-recommendation.js';

// Injection Budget Manager (context window health)
export {
  InjectionBudgetManager,
  createInjectionBudgetManager,
  type InjectionSlot,
  type InjectionBudgetConfig,
  type InjectionBudgetStats,
} from './budget/injection-budget.js';

// Thinking/Reflection Strategy (prompt engineering for reasoning)
export {
  generateThinkingDirectives,
  getThinkingSystemPrompt,
  getSubagentQualityPrompt,
  createThinkingStrategy,
  type ThinkingDirective,
  type ThinkingConfig,
} from './utilities/thinking-strategy.js';

// Subagent Output Store (bypass coordinator pattern)
export {
  SubagentOutputStore,
  createSubagentOutputStore,
  type SubagentOutput,
  type SubagentOutputStoreConfig,
} from './agents/subagent-output-store.js';

// Self-Improvement Protocol (tool failure diagnosis)
export {
  SelfImprovementProtocol,
  createSelfImprovementProtocol,
  type ToolCallDiagnosis,
  type FailureCategory as SelfImprovementFailureCategory,
  type SelfImprovementConfig,
  type SuccessPattern,
} from './quality/self-improvement.js';

// MCP Tool Validator (description quality checks)
export {
  validateToolDescription,
  validateAllTools,
  formatValidationSummary,
  createToolValidator,
  type ToolValidationResult,
  type ToolValidationConfig,
} from './mcp/mcp-tool-validator.js';

// MCP Custom Tools (API wrapper factory)
export {
  createSerperSearchTool,
  createCustomTool,
  createCustomTools,
  customToolToRegistryFormat,
  type CustomToolDefinition,
  type CustomToolResult,
  type CustomToolConfig,
  type SerperSearchConfig,
  type GenericToolSpec,
} from './mcp/mcp-custom-tools.js';

// Async Subagent Execution (non-blocking subagent handles)
export {
  createSubagentHandle,
  SubagentSupervisor,
  createSubagentSupervisor,
  type SubagentHandle,
  type SubagentProgress,
  type ProgressCallback,
  type AsyncSubagentConfig,
  type SubagentSupervisorConfig,
} from './agents/async-subagent.js';

// Auto-Checkpoint Resumption (crash recovery)
export {
  AutoCheckpointManager,
  createAutoCheckpointManager,
  type Checkpoint as AutoCheckpoint,
  type AutoCheckpointConfig,
  type ResumeCandidate,
} from './quality/auto-checkpoint.js';

// Dynamic Budget Rebalancing (starvation prevention)
export {
  DynamicBudgetPool,
  createDynamicBudgetPool,
  type DynamicBudgetConfig,
  type ChildPriority,
  type RebalanceResult,
} from './budget/dynamic-budget.js';

// Structured Logger (leveled logging with trace IDs and multiple sinks)
export {
  StructuredLogger,
  ConsoleSink,
  MemorySink,
  FileSink,
  logger,
  configureLogger,
  createComponentLogger,
  type LogLevel,
  type LogEntry,
  type LogSink,
  type LoggerConfig,
} from './utilities/logger.js';

// Environment Facts (temporal/platform grounding for all agents)
export {
  getEnvironmentFacts,
  refreshEnvironmentFacts,
  formatFactsBlock,
  formatFactsCompact,
  type EnvironmentFacts,
} from './utilities/environment-facts.js';
