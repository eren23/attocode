/**
 * Lesson 22: Model Routing Types
 *
 * Types for intelligent model selection, capability matching,
 * and fallback handling.
 */

// =============================================================================
// MODEL CAPABILITIES
// =============================================================================

/**
 * Model capability profile.
 */
export interface ModelCapability {
  /** Model identifier (e.g., 'claude-3-sonnet', 'gpt-4') */
  model: string;

  /** Provider (e.g., 'anthropic', 'openai') */
  provider: string;

  /** Maximum context window */
  maxTokens: number;

  /** Maximum output tokens */
  maxOutputTokens: number;

  /** Supports function/tool calling */
  supportsTools: boolean;

  /** Supports image/vision input */
  supportsVision: boolean;

  /** Supports structured JSON output */
  supportsStructuredOutput: boolean;

  /** Supports streaming responses */
  supportsStreaming: boolean;

  /** Cost per 1K input tokens (USD) */
  costPer1kInput: number;

  /** Cost per 1K output tokens (USD) */
  costPer1kOutput: number;

  /** Average latency in milliseconds */
  latencyMs: number;

  /** Quality score (0-100) based on benchmarks */
  qualityScore: number;

  /** Reliability score (0-100) based on uptime */
  reliabilityScore: number;

  /** Rate limit (requests per minute) */
  rateLimit: number;

  /** Tags for categorization */
  tags: string[];
}

/**
 * Task context for routing decisions.
 */
export interface TaskContext {
  /** Task description or goal */
  task: string;

  /** Estimated input tokens */
  estimatedInputTokens: number;

  /** Expected output size */
  expectedOutputSize: 'small' | 'medium' | 'large';

  /** Requires tool use */
  requiresTools: boolean;

  /** Requires vision/image processing */
  requiresVision: boolean;

  /** Requires structured output */
  requiresStructuredOutput: boolean;

  /** Task complexity */
  complexity: 'simple' | 'moderate' | 'complex';

  /** Quality requirement */
  qualityRequirement: 'low' | 'medium' | 'high' | 'maximum';

  /** Latency requirement */
  latencyRequirement: 'fast' | 'normal' | 'relaxed';

  /** Budget constraint (max cost in USD) */
  maxCost?: number;

  /** Task type for specialized routing */
  taskType?: TaskType;

  /** Additional metadata */
  metadata?: Record<string, unknown>;
}

/**
 * Task types for specialized routing.
 */
export type TaskType =
  | 'code_generation'
  | 'code_review'
  | 'summarization'
  | 'translation'
  | 'analysis'
  | 'creative_writing'
  | 'chat'
  | 'extraction'
  | 'classification'
  | 'reasoning'
  | 'general';

// =============================================================================
// ROUTING RULES
// =============================================================================

/**
 * Routing rule for matching tasks to models.
 */
export interface RoutingRule {
  /** Rule name for debugging */
  name: string;

  /** Condition function */
  condition: (task: TaskContext) => boolean;

  /** Model to use when condition matches */
  model: string;

  /** Priority (lower = higher priority) */
  priority: number;

  /** Whether this rule is enabled */
  enabled: boolean;

  /** Optional description */
  description?: string;
}

/**
 * Routing decision result.
 */
export interface RoutingDecision {
  /** Selected model */
  model: string;

  /** Reason for selection */
  reason: string;

  /** Matched rule (if any) */
  matchedRule?: string;

  /** Alternative models considered */
  alternatives: ModelAlternative[];

  /** Estimated cost */
  estimatedCost: number;

  /** Confidence score (0-1) */
  confidence: number;
}

/**
 * Alternative model option.
 */
export interface ModelAlternative {
  model: string;
  score: number;
  reason: string;
}

// =============================================================================
// FALLBACK CONFIGURATION
// =============================================================================

/**
 * Fallback chain configuration.
 */
export interface FallbackConfig {
  /** Primary model */
  primary: string;

  /** Fallback models in order of preference */
  fallbacks: string[];

  /** When to trigger fallback */
  triggers: FallbackTrigger[];

  /** Maximum retry attempts per model */
  maxRetriesPerModel: number;

  /** Delay between retries (ms) */
  retryDelayMs: number;

  /** Whether to use exponential backoff */
  exponentialBackoff: boolean;
}

/**
 * Conditions that trigger fallback.
 */
export type FallbackTrigger =
  | 'rate_limit'
  | 'timeout'
  | 'error'
  | 'overload'
  | 'unavailable'
  | 'context_too_long'
  | 'cost_exceeded';

/**
 * Fallback execution result.
 */
export interface FallbackResult<T> {
  /** The result (if successful) */
  result?: T;

  /** Model that succeeded */
  successModel?: string;

  /** Models that were attempted */
  attemptedModels: ModelAttempt[];

  /** Whether any model succeeded */
  success: boolean;

  /** Total time spent across all attempts */
  totalTimeMs: number;

  /** Total cost incurred */
  totalCost: number;
}

/**
 * Single model attempt result.
 */
export interface ModelAttempt {
  model: string;
  success: boolean;
  error?: string;
  errorType?: FallbackTrigger;
  durationMs: number;
  cost: number;
  retries: number;
}

// =============================================================================
// COST OPTIMIZATION
// =============================================================================

/**
 * Cost optimization configuration.
 */
export interface CostConfig {
  /** Daily budget (USD) */
  dailyBudget: number;

  /** Per-request budget (USD) */
  perRequestBudget?: number;

  /** Alert threshold (percentage of budget) */
  alertThreshold: number;

  /** Whether to prefer cheaper models */
  optimizeForCost: boolean;

  /** Minimum quality score to consider */
  minimumQualityScore: number;
}

/**
 * Cost tracking state.
 */
export interface CostState {
  /** Daily spending so far */
  dailySpend: number;

  /** Monthly spending so far */
  monthlySpend: number;

  /** Request count today */
  requestsToday: number;

  /** Last reset timestamp */
  lastReset: number;

  /** Cost by model */
  costByModel: Record<string, number>;
}

/**
 * Cost estimate for a task.
 */
export interface CostEstimate {
  model: string;
  inputCost: number;
  outputCost: number;
  totalCost: number;
  isWithinBudget: boolean;
  budgetRemaining: number;
}

// =============================================================================
// MODEL REGISTRY
// =============================================================================

/**
 * Model registry for capability lookup.
 */
export interface ModelRegistry {
  /** Get capability for a model */
  getCapability(model: string): ModelCapability | undefined;

  /** List all models */
  listModels(): ModelCapability[];

  /** Find models matching requirements */
  findModels(requirements: ModelRequirements): ModelCapability[];

  /** Register a new model */
  register(capability: ModelCapability): void;

  /** Update model capability */
  update(model: string, updates: Partial<ModelCapability>): void;

  /** Remove a model */
  remove(model: string): boolean;
}

/**
 * Requirements for model filtering.
 */
export interface ModelRequirements {
  /** Minimum context size */
  minTokens?: number;

  /** Must support tools */
  requiresTools?: boolean;

  /** Must support vision */
  requiresVision?: boolean;

  /** Must support structured output */
  requiresStructuredOutput?: boolean;

  /** Maximum cost per 1K tokens */
  maxCostPer1k?: number;

  /** Maximum latency */
  maxLatencyMs?: number;

  /** Minimum quality score */
  minQualityScore?: number;

  /** Required tags */
  tags?: string[];

  /** Specific providers */
  providers?: string[];
}

// =============================================================================
// ROUTER INTERFACE
// =============================================================================

/**
 * Model router interface.
 */
export interface ModelRouter {
  /** Route a task to a model */
  route(task: TaskContext): Promise<RoutingDecision>;

  /** Add a routing rule */
  addRule(rule: RoutingRule): void;

  /** Remove a routing rule */
  removeRule(name: string): boolean;

  /** Configure fallback chain */
  withFallback(config: FallbackConfig): ModelRouter;

  /** Configure cost optimization */
  withCostOptimization(config: CostConfig): ModelRouter;

  /** Get routing statistics */
  getStats(): RouterStats;
}

/**
 * Router statistics.
 */
export interface RouterStats {
  totalRequests: number;
  routingsByModel: Record<string, number>;
  averageLatencyMs: number;
  fallbackRate: number;
  totalCost: number;
  costByModel: Record<string, number>;
  ruleHitRate: Record<string, number>;
}

// =============================================================================
// EVENTS
// =============================================================================

/**
 * Router events for observability.
 */
export type RouterEvent =
  | { type: 'route.decision'; decision: RoutingDecision; task: TaskContext }
  | { type: 'fallback.triggered'; trigger: FallbackTrigger; fromModel: string; toModel: string }
  | { type: 'fallback.exhausted'; attempts: ModelAttempt[] }
  | { type: 'cost.alert'; current: number; threshold: number; budget: number }
  | { type: 'model.unavailable'; model: string; reason: string }
  | { type: 'model.recovered'; model: string };

export type RouterEventListener = (event: RouterEvent) => void;

// =============================================================================
// DEFAULT MODEL CAPABILITIES
// =============================================================================

/**
 * Default model capability profiles.
 * These are approximate values - actual values may vary.
 */
export const DEFAULT_MODEL_CAPABILITIES: ModelCapability[] = [
  {
    model: 'claude-3-opus',
    provider: 'anthropic',
    maxTokens: 200000,
    maxOutputTokens: 4096,
    supportsTools: true,
    supportsVision: true,
    supportsStructuredOutput: true,
    supportsStreaming: true,
    costPer1kInput: 0.015,
    costPer1kOutput: 0.075,
    latencyMs: 2000,
    qualityScore: 95,
    reliabilityScore: 98,
    rateLimit: 50,
    tags: ['premium', 'reasoning', 'coding', 'analysis'],
  },
  {
    model: 'claude-3-sonnet',
    provider: 'anthropic',
    maxTokens: 200000,
    maxOutputTokens: 4096,
    supportsTools: true,
    supportsVision: true,
    supportsStructuredOutput: true,
    supportsStreaming: true,
    costPer1kInput: 0.003,
    costPer1kOutput: 0.015,
    latencyMs: 1000,
    qualityScore: 85,
    reliabilityScore: 98,
    rateLimit: 100,
    tags: ['balanced', 'coding', 'general'],
  },
  {
    model: 'claude-3-haiku',
    provider: 'anthropic',
    maxTokens: 200000,
    maxOutputTokens: 4096,
    supportsTools: true,
    supportsVision: true,
    supportsStructuredOutput: true,
    supportsStreaming: true,
    costPer1kInput: 0.00025,
    costPer1kOutput: 0.00125,
    latencyMs: 500,
    qualityScore: 70,
    reliabilityScore: 99,
    rateLimit: 200,
    tags: ['fast', 'cheap', 'simple'],
  },
  {
    model: 'gpt-4-turbo',
    provider: 'openai',
    maxTokens: 128000,
    maxOutputTokens: 4096,
    supportsTools: true,
    supportsVision: true,
    supportsStructuredOutput: true,
    supportsStreaming: true,
    costPer1kInput: 0.01,
    costPer1kOutput: 0.03,
    latencyMs: 1500,
    qualityScore: 90,
    reliabilityScore: 95,
    rateLimit: 60,
    tags: ['premium', 'reasoning', 'coding'],
  },
  {
    model: 'gpt-4o',
    provider: 'openai',
    maxTokens: 128000,
    maxOutputTokens: 16384,
    supportsTools: true,
    supportsVision: true,
    supportsStructuredOutput: true,
    supportsStreaming: true,
    costPer1kInput: 0.005,
    costPer1kOutput: 0.015,
    latencyMs: 800,
    qualityScore: 88,
    reliabilityScore: 96,
    rateLimit: 100,
    tags: ['balanced', 'fast', 'vision'],
  },
  {
    model: 'gpt-3.5-turbo',
    provider: 'openai',
    maxTokens: 16384,
    maxOutputTokens: 4096,
    supportsTools: true,
    supportsVision: false,
    supportsStructuredOutput: true,
    supportsStreaming: true,
    costPer1kInput: 0.0005,
    costPer1kOutput: 0.0015,
    latencyMs: 400,
    qualityScore: 60,
    reliabilityScore: 97,
    rateLimit: 300,
    tags: ['fast', 'cheap', 'simple'],
  },
];
