/**
 * Core Agent Context Types
 *
 * Defines the AgentContext interface — the dependency bundle passed to extracted
 * modules (execution-loop, tool-executor, response-handler, subagent-spawner).
 * This avoids circular imports and massive parameter lists while keeping
 * modules decoupled from the ProductionAgent class.
 */

import type {
  ToolDefinition,
  AgentState,
  AgentEvent,
  AgentEventListener,
  AgentResult,
  AgentMetrics,
  LLMProvider,
  ProductionAgentConfig,
} from '../types.js';

import type { buildConfig } from '../defaults.js';
import type { ModeManager, AgentMode } from '../modes.js';

// Re-export integration types used by extracted modules
import type {
  HookManager,
  ExecutionEconomicsManager,
  CancellationManager,
  ResourceManager,
  SafetyManager,
  ObservabilityManager,
  ContextEngineeringManager,
  PendingPlanManager,
  ExecutionPolicyManager,
  SharedBlackboard,
  SharedFileCache,
  SharedBudgetPool,
  WorkLog,
  VerificationGate,
  AutoCompactionManager,
  AgentRegistry,
  RoutingManager,
  PlanningManager,
  MemoryManager,
  ToolRecommendationEngine,
  InjectionBudgetManager,
  SelfImprovementProtocol,
  SubagentOutputStore,
  AutoCheckpointManager,
  CodebaseContextManager,
  LearningStore,
  Compactor,
  SkillManager,
  SemanticCacheManager,
  LSPManager,
  TaskManager,
  InteractivePlanner,
  RecursiveContextManager,
  FileChangeTracker,
  CapabilitiesRegistry,
  CancellationTokenType,
  CacheableContentBlock,
  ComplexityAssessment,
  SQLiteStore,
  ApprovalScope,
  PendingPlan,
} from '../integrations/index.js';

import type { TraceCollector } from '../tracing/trace-collector.js';
import type { AgentStateMachine } from './agent-state-machine.js';

// =============================================================================
// AGENT CONTEXT — Shared dependency bundle for extracted modules
// =============================================================================

/**
 * Read-only snapshot of agent configuration and runtime dependencies.
 * Extracted modules receive this context — they never hold a reference
 * to ProductionAgent itself, preventing circular dependencies.
 *
 * Fields mirror the private fields of ProductionAgent. Nullable fields
 * match the `| null` pattern already used in agent.ts.
 */
export interface AgentContext {
  // --- Configuration ---
  readonly config: ReturnType<typeof buildConfig>;
  readonly agentId: string;

  // --- Core runtime ---
  readonly provider: LLMProvider;
  readonly tools: Map<string, ToolDefinition>;
  readonly state: AgentState;

  // --- Mode management ---
  readonly modeManager: ModeManager;
  readonly pendingPlanManager: PendingPlanManager;

  // --- Manager references (nullable, matching agent.ts pattern) ---
  readonly hooks: HookManager | null;
  readonly economics: ExecutionEconomicsManager | null;
  readonly cancellation: CancellationManager | null;
  readonly resourceManager: ResourceManager | null;
  readonly safety: SafetyManager | null;
  readonly observability: ObservabilityManager | null;
  readonly contextEngineering: ContextEngineeringManager | null;
  readonly traceCollector: TraceCollector | null;
  readonly executionPolicy: ExecutionPolicyManager | null;
  readonly routing: RoutingManager | null;
  readonly planning: PlanningManager | null;
  readonly memory: MemoryManager | null;
  readonly react: import('../integrations/index.js').ReActManager | null;

  // --- Coordination managers ---
  readonly blackboard: SharedBlackboard | null;
  readonly fileCache: SharedFileCache | null;
  readonly budgetPool: SharedBudgetPool | null;
  readonly taskManager: TaskManager | null;
  readonly store: SQLiteStore | null;

  // --- Context & codebase ---
  readonly codebaseContext: CodebaseContextManager | null;
  readonly learningStore: LearningStore | null;
  readonly compactor: Compactor | null;
  readonly autoCompactionManager: AutoCompactionManager | null;
  readonly workLog: WorkLog | null;
  readonly verificationGate: VerificationGate | null;

  // --- Subagent infrastructure ---
  readonly agentRegistry: AgentRegistry | null;
  readonly toolRecommendation: ToolRecommendationEngine | null;
  readonly selfImprovement: SelfImprovementProtocol | null;
  readonly subagentOutputStore: SubagentOutputStore | null;
  readonly autoCheckpointManager: AutoCheckpointManager | null;
  readonly injectionBudget: InjectionBudgetManager | null;

  // --- State machine (Phase 2.2) ---
  readonly stateMachine: AgentStateMachine | null;

  // --- Other managers ---
  readonly skillManager: SkillManager | null;
  readonly semanticCache: SemanticCacheManager | null;
  readonly lspManager: LSPManager | null;
  readonly threadManager: import('../integrations/index.js').ThreadManager | null;
  readonly interactivePlanner: InteractivePlanner | null;
  readonly recursiveContext: RecursiveContextManager | null;
  readonly fileChangeTracker: FileChangeTracker | null;
  readonly typeCheckerState:
    | import('../integrations/safety/type-checker.js').TypeCheckerState
    | null;
  readonly capabilitiesRegistry: CapabilitiesRegistry | null;
  readonly rules: import('../integrations/index.js').RulesManager | null;

  // --- Mutable state owned by agent (extracted modules can mutate) ---
  readonly lastComplexityAssessment: ComplexityAssessment | null;
  readonly cacheableSystemBlocks: CacheableContentBlock[] | null;
  readonly parentIterations: number;
  readonly externalCancellationToken: CancellationTokenType | null;
  readonly wrapupRequested: boolean;
  readonly wrapupReason: string | null;
  readonly compactionPending: boolean;

  // --- Shared swarm state ---
  readonly sharedContextState: import('../shared/index.js').SharedContextState | null;
  readonly sharedEconomicsState: import('../shared/index.js').SharedEconomicsState | null;

  // --- Spawn dedup tracking ---
  readonly spawnedTasks: Map<string, { timestamp: number; result: string; queuedChanges: number }>;

  // --- Tool resolver for lazy MCP loading ---
  readonly toolResolver: ((toolName: string) => ToolDefinition | null) | null;

  // --- Callbacks that delegate to ProductionAgent methods ---
  emit: (event: AgentEvent) => void;
  addTool: (tool: ToolDefinition) => void;
  getMaxContextTokens: () => number;
  getTotalIterations: () => number;
}

/**
 * Mutable fields that extracted modules need to update.
 * ProductionAgent provides setter methods for these; extracted modules
 * call the setters rather than mutating the context directly.
 */
export interface AgentContextMutators {
  setBudgetPool: (pool: SharedBudgetPool | null) => void;
  setCacheableSystemBlocks: (blocks: CacheableContentBlock[] | null) => void;
  setCompactionPending: (pending: boolean) => void;
  setWrapupRequested: (requested: boolean) => void;
  setLastComplexityAssessment: (assessment: ComplexityAssessment | null) => void;
  setExternalCancellationToken: (token: CancellationTokenType | null) => void;
}

// =============================================================================
// SUBAGENT INTERFACE — Decouples subagent-spawner from ProductionAgent class
// =============================================================================

/**
 * Interface for a created subagent instance. The subagent-spawner module
 * programs against this interface so it doesn't need to import ProductionAgent
 * (which would create a circular dependency).
 */
export interface SubAgentInstance {
  run(task: string): Promise<AgentResult>;
  setMode(mode: AgentMode): void;
  setApprovalScope(scope: ApprovalScope): void;
  setParentIterations(iterations: number): void;
  setExternalCancellation(token: CancellationTokenType): void;
  setTraceCollector(collector: TraceCollector): void;
  subscribe(handler: AgentEventListener): () => void;
  requestWrapup(reason: string): void;
  hasPendingPlan(): boolean;
  getPendingPlan(): PendingPlan | null;
  getState(): AgentState;
  getMetrics(): AgentMetrics;
  getModifiedFilePaths(): string[];
  cleanup(): Promise<void>;
}

/**
 * Factory function that creates a SubAgentInstance from a config.
 * ProductionAgent passes `(config) => new ProductionAgent(config)` when
 * constructing the context, so the spawner never imports the class directly.
 */
export type SubAgentFactory = (
  config: Partial<ProductionAgentConfig> & { provider: LLMProvider },
) => SubAgentInstance;

// Note: No re-exports here to avoid name collisions with core/protocol.
// Extracted modules import directly from '../types.js' and '../integrations/index.js'.
