/**
 * Atomic Tricks - Standalone Utility Modules
 *
 * These modules can be integrated into lessons or used independently.
 * Each trick solves a common problem in AI agent development.
 */

// Trick A: Structured Output Parsing
export {
  parseStructured,
  extractJson,
  objectSchema,
  arraySchema,
  taskSchema,
  type Schema,
  type LLMProvider,
  type ParseOptions,
} from './structured-output.js';

// Trick B: Token Counting
export {
  countTokens,
  countConversationTokens,
  estimateCost,
  formatCost,
  estimateCallCost,
  createBudgetTracker,
  getModelPricing,
  type TokenCounts,
  type ModelPricing,
  type CostEstimate,
} from './token-counter.js';

// Trick C: Prompt Templates
export {
  compileTemplate,
  template,
  joinTemplates,
  PROMPT_TEMPLATES,
  type CompiledTemplate,
  type TemplateOptions,
} from './prompt-templates.js';

// Trick D: Tool Call Batching
export {
  executeBatch,
  executeParallel,
  executeSequential,
  executeWithDependencies,
  executeWithRetry,
  createToolRegistry,
  groupResults,
  type ToolCall,
  type ToolResult,
  type ToolDefinition,
  type ToolRegistry,
  type BatchOptions,
  type DependentToolCall,
  type RetryOptions,
} from './tool-batching.js';

// Trick E: Context Window Sliding
export {
  slideWindow,
  createContextWindow,
  type Message as ContextMessage,
  type SlidingStrategy,
  type SlidingOptions,
  type SlidingResult,
} from './context-sliding.js';

// Trick F: Semantic Caching
export {
  SemanticCache,
  createSemanticCache,
  cosineSimilarity,
  withCache,
  type CacheEntry,
  type CacheHit,
  type CacheOptions,
  type EmbeddingFunction,
} from './semantic-cache.js';

// Trick G: Rate Limit Handling
export {
  RateLimiter,
  createRateLimiter,
  PROVIDER_LIMITS,
  type RateLimiterConfig,
  type RateLimitStatus,
} from './rate-limiter.js';

// Trick H: Conversation Branching
export {
  ConversationTree,
  createConversationTree,
  type Message as BranchMessage,
  type Branch,
  type MergeStrategy,
  type BranchInfo,
} from './branching.js';

// Trick I: File Watcher Integration
export {
  watchProject,
  watchProjectBatched,
  watchFileTypes,
  BatchedWatcher,
  type FileEvent,
  type FileChangeCallback,
  type Disposable,
  type WatcherOptions,
} from './file-watcher.js';

// Trick J: LSP Integration
export {
  SimpleLSPClient,
  createLSPClient,
  type Position,
  type Range,
  type Location,
  type Diagnostic,
  type DiagnosticSeverity,
  type Completion,
  type CompletionKind,
  type LSPClientOptions,
} from './lsp-client.js';

// Trick K: Cancellation Tokens
export {
  createCancellationTokenSource,
  createTimeoutToken,
  createLinkedToken,
  withCancellation,
  sleep,
  race,
  CancellationError,
  type CancellationToken,
  type CancellationTokenSource,
} from './cancellation.js';

// Trick L: Sortable IDs
export {
  generateId,
  generateBatch,
  getTimestamp,
  compareIds,
  isAfter,
  isBefore,
  createIdGenerator,
  idGenerators,
  isValidId,
  parseId,
} from './sortable-id.js';

// Trick M: Thread Manager
export {
  SimpleThreadManager,
  createThreadManager,
  createWithHistory,
  type Message as ThreadMessage,
  type Thread,
} from './thread-manager.js';

// Trick N: Resource Monitor
export {
  SimpleResourceMonitor,
  createResourceMonitor,
  createStrictMonitor,
  createLenientMonitor,
  ResourceLimitError,
  type ResourceLimits,
  type ResourceUsage,
  type ResourceStatus,
  type ResourceCheck,
} from './resource-monitor.js';

// Trick O: JSON Utilities
export {
  extractJsonObject,
  extractAllJsonObjects,
  safeParseJson,
  extractToolCallJson,
  extractAllToolCalls,
  type SafeParseOptions,
  type SafeParseResult,
  type ToolCall,
} from './json-utils.js';

// Trick P: KV-Cache Aware Context
export {
  CacheAwareContext,
  createCacheAwareContext,
  stableStringify,
  normalizeJson,
  analyzeCacheEfficiency,
  formatCacheStats,
  createEndTimestamp,
  type CacheAwareConfig,
  type CacheBreakpoint,
  type DynamicContent,
  type CacheStats,
  type ContextMessage,
  type CacheEvent,
} from './kv-cache-context.js';

// Trick Q: Recitation / Goal Reinforcement
export {
  RecitationManager,
  createRecitationManager,
  buildQuickRecitation,
  calculateOptimalFrequency,
  formatRecitationHistory,
  type RecitationConfig,
  type RecitationSource,
  type RecitationState,
  type PlanState,
  type PlanTask,
  type TodoItem,
  type RecitationEvent,
} from './recitation.js';

// Trick R: Reversible Compaction
export {
  ReversibleCompactor,
  createReversibleCompactor,
  extractReferences,
  extractFileReferences,
  extractUrlReferences,
  extractFunctionReferences,
  extractErrorReferences,
  extractCommandReferences,
  createReconstructionPrompt,
  calculateRelevance,
  formatCompactionStats,
  quickExtract,
  type Reference,
  type ReferenceType,
  type ReversibleCompactionConfig,
  type CompactionResult,
  type CompactionStats,
  type CompactionEvent,
} from './reversible-compaction.js';

// Trick S: Failure Evidence Preservation
export {
  FailureTracker,
  createFailureTracker,
  categorizeError,
  generateSuggestion,
  formatFailureContext,
  createRepeatWarning,
  extractInsights,
  formatFailureStats,
  type Failure,
  type FailureCategory,
  type FailureTrackerConfig,
  type FailureInput,
  type FailurePattern,
  type FailureEvent,
} from './failure-evidence.js';

// Trick T: Serialization Diversity
export {
  DiverseSerializer,
  createDiverseSerializer,
  serializeWithVariation,
  generateVariations,
  diversifyToolArgs,
  diversifyToolResult,
  formatDiversityStats,
  areSemanticEquivalent,
  type DiverseSerializerConfig,
  type SerializationStyle,
  type DiversityStats,
  type SerializerEvent,
} from './serialization-diversity.js';
