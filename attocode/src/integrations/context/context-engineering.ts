/**
 * Context Engineering Integration
 *
 * Integrates the Manus-inspired context engineering tricks (P, Q, R, S, T)
 * into the production agent for improved performance and reliability.
 *
 * Features:
 * - P: KV-Cache Aware Context - ~10x cost reduction on cached tokens
 * - Q: Recitation / Goal Reinforcement - Combat "lost in middle" attention
 * - R: Reversible Compaction - Preserve retrieval keys during summarization
 * - S: Failure Evidence Preservation - Learn from mistakes, avoid loops
 * - T: Serialization Diversity - Prevent few-shot pattern collapse
 */

import {
  CacheAwareContext,
  createCacheAwareContext,
  stableStringify,
  analyzeCacheEfficiency,
  type CacheStats,
  type CacheableContentBlock,
} from '../../tricks/kv-cache-context.js';

import {
  RecitationManager,
  createRecitationManager,
  calculateOptimalFrequency,
  type RecitationState,
} from '../../tricks/recitation.js';

import {
  ReversibleCompactor,
  createReversibleCompactor,
  createReconstructionPrompt,
  type Reference,
  type CompactionResult,
} from '../../tricks/reversible-compaction.js';

import {
  FailureTracker,
  createFailureTracker,
  extractInsights,
  type Failure,
  type FailurePattern,
} from '../../tricks/failure-evidence.js';

import {
  DiverseSerializer,
  createDiverseSerializer,
  type DiversityStats,
} from '../../tricks/serialization-diversity.js';

import type { SharedContextState } from '../../shared/shared-context-state.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Configuration for context engineering.
 */
export interface ContextEngineeringConfig {
  /** Enable KV-cache optimization */
  enableCacheOptimization?: boolean;

  /** Enable periodic goal recitation */
  enableRecitation?: boolean;

  /** Enable reversible compaction */
  enableReversibleCompaction?: boolean;

  /** Enable failure tracking */
  enableFailureTracking?: boolean;

  /** Enable serialization diversity */
  enableDiversity?: boolean;

  /** Static prefix for system prompt (for cache optimization) */
  staticPrefix?: string;

  /** Recitation frequency (iterations) */
  recitationFrequency?: number;

  /** Diversity level (0-1) */
  diversityLevel?: number;

  /** Maximum failures to track */
  maxFailures?: number;

  /** Maximum references to preserve during compaction */
  maxReferences?: number;
}

/**
 * Message format for context engineering.
 */
export interface ContextMessage {
  role: 'system' | 'user' | 'assistant' | 'tool';
  content: string;
  name?: string;
}

/**
 * Context engineering statistics.
 */
export interface ContextEngineeringStats {
  /** KV-cache statistics */
  cache?: CacheStats;

  /** Recitation injection count */
  recitationInjections: number;

  /** Preserved references from compaction */
  preservedReferences: number;

  /** Tracked failures */
  trackedFailures: number;

  /** Unresolved failures */
  unresolvedFailures: number;

  /** Failure patterns detected */
  patternsDetected: number;

  /** Serialization diversity stats */
  diversity?: DiversityStats;
}

/**
 * Events emitted by context engineering manager.
 */
export type ContextEngineeringEvent =
  | { type: 'recitation.injected'; iteration: number }
  | { type: 'failure.recorded'; failure: Failure }
  | { type: 'failure.pattern'; pattern: FailurePattern }
  | { type: 'compaction.completed'; references: number }
  | { type: 'cache.warning'; warning: string };

export type ContextEngineeringEventListener = (event: ContextEngineeringEvent) => void;

// =============================================================================
// CONTEXT ENGINEERING MANAGER
// =============================================================================

/**
 * Unified manager for all context engineering features.
 */
export class ContextEngineeringManager {
  private config: Required<ContextEngineeringConfig>;

  // Sub-managers
  private cacheContext?: CacheAwareContext;
  private recitation?: RecitationManager;
  private compactor?: ReversibleCompactor;
  private failureTracker?: FailureTracker;
  private serializer?: DiverseSerializer;

  // Shared state (optional, injected for swarm workers)
  private sharedState: SharedContextState | null = null;

  // State
  private iteration = 0;
  private recitationInjections = 0;
  private patternsDetected = 0;
  private listeners: ContextEngineeringEventListener[] = [];

  constructor(config: ContextEngineeringConfig = {}) {
    this.config = {
      enableCacheOptimization: config.enableCacheOptimization ?? true,
      enableRecitation: config.enableRecitation ?? true,
      enableReversibleCompaction: config.enableReversibleCompaction ?? true,
      enableFailureTracking: config.enableFailureTracking ?? true,
      enableDiversity: config.enableDiversity ?? false, // Off by default
      staticPrefix: config.staticPrefix ?? 'You are a helpful AI assistant.',
      recitationFrequency: config.recitationFrequency ?? 5,
      diversityLevel: config.diversityLevel ?? 0.2,
      maxFailures: config.maxFailures ?? 30,
      maxReferences: config.maxReferences ?? 50,
    };

    this.initializeSubManagers();
  }

  /**
   * Initialize sub-managers based on config.
   */
  private initializeSubManagers(): void {
    if (this.config.enableCacheOptimization) {
      this.cacheContext = createCacheAwareContext({
        staticPrefix: this.config.staticPrefix,
        cacheBreakpoints: ['system_end', 'tools_end', 'rules_end'],
        deterministicJson: true,
        enforceAppendOnly: true,
      });
    }

    if (this.config.enableRecitation) {
      this.recitation = createRecitationManager({
        frequency: this.config.recitationFrequency,
        sources: ['goal', 'plan', 'todo'],
        maxTokens: 500,
        trackHistory: true,
      });
    }

    if (this.config.enableReversibleCompaction) {
      this.compactor = createReversibleCompactor({
        preserveTypes: ['file', 'url', 'function', 'error', 'command'],
        maxReferences: this.config.maxReferences,
        deduplicate: true,
      });
    }

    if (this.config.enableFailureTracking) {
      this.failureTracker = createFailureTracker({
        maxFailures: this.config.maxFailures,
        preserveStackTraces: true,
        detectRepeats: true,
        repeatWarningThreshold: 3,
      });

      // Listen for patterns
      this.failureTracker.on((event) => {
        if (event.type === 'pattern.detected') {
          this.patternsDetected++;
          this.emit({ type: 'failure.pattern', pattern: event.pattern });
        }
      });
    }

    if (this.config.enableDiversity) {
      this.serializer = createDiverseSerializer({
        variationLevel: this.config.diversityLevel,
        preserveSemantics: true,
        varyKeyOrder: true,
        varyIndentation: true,
      });
    }
  }

  /**
   * Bind to shared state for cross-worker failure learning and reference pooling.
   * Called after construction when a worker joins a swarm.
   * Replaces the local failure tracker with the shared one.
   */
  setSharedState(shared: SharedContextState): void {
    this.sharedState = shared;
    // Replace local failure tracker with shared one so all workers
    // read/write to the same tracker
    if (this.failureTracker) {
      this.failureTracker = shared.getFailureTracker();
    }
  }

  /**
   * Build a cache-optimized system prompt.
   */
  buildSystemPrompt(options: {
    rules?: string;
    tools?: string;
    memory?: string;
    dynamic?: Record<string, string>;
  }): string {
    if (!this.cacheContext) {
      // Fallback: simple concatenation
      const parts = [this.config.staticPrefix];
      if (options.rules) parts.push('\n\n## Rules\n' + options.rules);
      if (options.tools) parts.push('\n\n## Tools\n' + options.tools);
      if (options.memory) parts.push('\n\n## Context\n' + options.memory);
      if (options.dynamic) {
        const dynamicParts = Object.entries(options.dynamic)
          .map(([k, v]) => `${k}: ${v}`)
          .join(' | ');
        parts.push('\n\n---\n' + dynamicParts);
      }
      return parts.join('');
    }

    // Analyze for warnings
    const systemPrompt = this.cacheContext.buildSystemPrompt(options);
    const analysis = analyzeCacheEfficiency(systemPrompt);
    for (const warning of analysis.warnings) {
      this.emit({ type: 'cache.warning', warning });
    }

    return systemPrompt;
  }

  /**
   * Build a cache-optimized system prompt as CacheableContent blocks.
   * Each section gets a `cache_control: { type: 'ephemeral' }` marker
   * so the LLM provider can use prompt caching (60-70% cost reduction).
   *
   * Falls back to a single text block (no cache markers) if KV-cache
   * context is not configured.
   */
  buildCacheableSystemPrompt(options: {
    rules?: string;
    tools?: string;
    memory?: string;
    dynamic?: Record<string, string>;
  }): CacheableContentBlock[] {
    if (!this.cacheContext) {
      // No KV-cache context configured — return empty array to signal
      // "no caching available". The caller (agent.ts) will fall back to
      // a plain string system message instead of sending unmarked blocks.
      return [];
    }

    return this.cacheContext.buildCacheableSystemPrompt(options);
  }

  /**
   * Serialize data with optional diversity.
   */
  serialize(data: unknown): string {
    if (this.serializer) {
      return this.serializer.serialize(data);
    }
    // Use stable stringify for cache efficiency
    return stableStringify(data);
  }

  /**
   * Inject recitation if needed.
   */
  injectRecitation(
    messages: ContextMessage[],
    state: Omit<RecitationState, 'iteration'>,
  ): ContextMessage[] {
    this.iteration++;

    if (!this.recitation) {
      return messages;
    }

    // Cast to compatible type - tool messages are preserved but not used in recitation
    const result = this.recitation.injectIfNeeded(
      messages as Array<{ role: 'system' | 'user' | 'assistant'; content: string }>,
      {
        ...state,
        iteration: this.iteration,
      },
    );

    if (result.length > messages.length) {
      this.recitationInjections++;
      this.emit({ type: 'recitation.injected', iteration: this.iteration });
    }

    return result;
  }

  /**
   * Update recitation frequency based on context size.
   */
  updateRecitationFrequency(contextTokens: number): void {
    if (this.recitation) {
      const frequency = calculateOptimalFrequency(contextTokens);
      this.recitation.updateConfig({ frequency });
    }
  }

  /**
   * Compact messages with reference preservation.
   */
  async compact(
    messages: ContextMessage[],
    summarize: (msgs: ContextMessage[]) => Promise<string>,
  ): Promise<{
    summary: string;
    references: Reference[];
    reconstructionPrompt: string;
  }> {
    if (!this.compactor) {
      // Fallback: simple summarization
      const summary = await summarize(messages);
      return {
        summary,
        references: [],
        reconstructionPrompt: '',
      };
    }

    const result = await this.compactor.compact(messages, { summarize });

    // Push references to shared pool for cross-worker access
    if (this.sharedState && result.references.length > 0) {
      this.sharedState.addReferences(result.references);
    }

    this.emit({
      type: 'compaction.completed',
      references: result.references.length,
    });

    return {
      summary: result.summary,
      references: result.references,
      reconstructionPrompt: createReconstructionPrompt(result.references),
    };
  }

  /**
   * Search preserved references.
   */
  searchReferences(query: string): Reference[] {
    return this.compactor?.searchReferences(query) || [];
  }

  /**
   * Get preserved references by type.
   */
  getReferencesByType(type: string): Reference[] {
    return this.compactor?.getReferencesByType(type as any) || [];
  }

  /**
   * Record a failure.
   */
  recordFailure(input: {
    action: string;
    args?: Record<string, unknown>;
    error: string | Error;
    intent?: string;
  }): Failure | null {
    if (!this.failureTracker) {
      return null;
    }

    const failure = this.failureTracker.recordFailure({
      ...input,
      iteration: this.iteration,
    });

    this.emit({ type: 'failure.recorded', failure });

    return failure;
  }

  /**
   * Get failure context for LLM inclusion.
   */
  getFailureContext(maxFailures: number = 10): string {
    return this.failureTracker?.getFailureContext({ maxFailures }) || '';
  }

  /**
   * Check if an action has failed recently.
   */
  hasRecentFailure(action: string): boolean {
    return this.failureTracker?.hasRecentFailure(action, 120000) || false;
  }

  /**
   * Get actionable insights from failures.
   */
  getFailureInsights(): string[] {
    if (!this.failureTracker) return [];
    return extractInsights(this.failureTracker.getUnresolvedFailures());
  }

  /**
   * Mark a failure as resolved.
   */
  resolveFailure(failureId: string): boolean {
    return this.failureTracker?.resolveFailure(failureId) || false;
  }

  /**
   * Get the underlying failure tracker for external integrations.
   * Useful for connecting to LearningStore for cross-session learning.
   */
  getFailureTracker(): FailureTracker | undefined {
    return this.failureTracker;
  }

  /**
   * Get current statistics.
   */
  getStats(): ContextEngineeringStats {
    const stats: ContextEngineeringStats = {
      recitationInjections: this.recitationInjections,
      preservedReferences: this.compactor?.getPreservedReferences().length || 0,
      trackedFailures: this.failureTracker?.getStats().total || 0,
      unresolvedFailures: this.failureTracker?.getStats().unresolved || 0,
      patternsDetected: this.patternsDetected,
    };

    if (this.serializer) {
      stats.diversity = this.serializer.getStats();
    }

    return stats;
  }

  /**
   * Get current iteration.
   */
  getIteration(): number {
    return this.iteration;
  }

  /**
   * Reset iteration counter (e.g., for new session).
   */
  resetIteration(): void {
    this.iteration = 0;
    this.recitationInjections = 0;
  }

  /**
   * Clear all tracked state.
   */
  clear(): void {
    this.iteration = 0;
    this.recitationInjections = 0;
    this.patternsDetected = 0;
    this.cacheContext?.reset();
    this.recitation?.clearHistory();
    this.compactor?.clear();
    this.failureTracker?.clear();
    this.serializer?.resetStats();
  }

  /**
   * Subscribe to events.
   */
  on(listener: ContextEngineeringEventListener): () => void {
    this.listeners.push(listener);
    return () => {
      const idx = this.listeners.indexOf(listener);
      if (idx >= 0) this.listeners.splice(idx, 1);
    };
  }

  private emit(event: ContextEngineeringEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch {
        // Ignore listener errors
      }
    }
  }
}

// =============================================================================
// FACTORY FUNCTIONS
// =============================================================================

/**
 * Create a context engineering manager.
 *
 * @example
 * ```typescript
 * const contextEng = createContextEngineering({
 *   enableCacheOptimization: true,
 *   enableRecitation: true,
 *   enableFailureTracking: true,
 *   staticPrefix: 'You are a coding assistant.',
 *   recitationFrequency: 5,
 * });
 *
 * // Build cache-optimized system prompt
 * const systemPrompt = contextEng.buildSystemPrompt({
 *   rules: rulesContent,
 *   tools: toolDescriptions,
 *   dynamic: { sessionId: 'abc123' },
 * });
 *
 * // Inject recitation during agent loop
 * const messages = contextEng.injectRecitation(currentMessages, {
 *   goal: 'Implement user auth',
 *   plan: currentPlan,
 *   todos: currentTodos,
 * });
 *
 * // Record failures
 * try {
 *   await tool.execute(args);
 * } catch (error) {
 *   contextEng.recordFailure({
 *     action: tool.name,
 *     args,
 *     error,
 *   });
 * }
 *
 * // Include failure context in prompts
 * const failureContext = contextEng.getFailureContext();
 * ```
 */
export function createContextEngineering(
  config: ContextEngineeringConfig = {},
): ContextEngineeringManager {
  return new ContextEngineeringManager(config);
}

/**
 * Create a minimal context engineering manager for testing.
 */
export function createMinimalContextEngineering(): ContextEngineeringManager {
  return new ContextEngineeringManager({
    enableCacheOptimization: false,
    enableRecitation: false,
    enableReversibleCompaction: false,
    enableFailureTracking: true, // Keep failure tracking
    enableDiversity: false,
  });
}

/**
 * Create a full-featured context engineering manager.
 */
export function createFullContextEngineering(staticPrefix: string): ContextEngineeringManager {
  return new ContextEngineeringManager({
    enableCacheOptimization: true,
    enableRecitation: true,
    enableReversibleCompaction: true,
    enableFailureTracking: true,
    enableDiversity: true,
    staticPrefix,
    diversityLevel: 0.2,
    recitationFrequency: 5,
    maxFailures: 50,
    maxReferences: 100,
  });
}

// =============================================================================
// EXPORTS
// =============================================================================

export {
  // Re-export from tricks for convenience
  stableStringify,
  calculateOptimalFrequency,
  createReconstructionPrompt,
  extractInsights,
};

// Re-export cache types for use in agent.ts and providers
export type { CacheableContentBlock } from '../../tricks/kv-cache-context.js';
