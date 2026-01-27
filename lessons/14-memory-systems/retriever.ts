/**
 * Lesson 14: Memory Retriever
 *
 * Retrieves memories using different strategies.
 * Combines recency, relevance, importance, and frequency.
 *
 * USER CONTRIBUTION OPPORTUNITY:
 * The hybrid retrieval strategy combines multiple factors.
 * You could implement:
 * - Custom weighting for hybrid scoring
 * - Embedding-based semantic search
 * - Context-aware retrieval
 */

import type {
  MemoryStore,
  MemoryEntry,
  RetrievalOptions,
  RetrievalResult,
  ScoredMemory,
  RetrievalStrategy,
  DEFAULT_RETRIEVAL_OPTIONS,
} from './types.js';

// =============================================================================
// MEMORY RETRIEVER
// =============================================================================

/**
 * Retrieves memories using configurable strategies.
 */
export class MemoryRetriever {
  private store: MemoryStore;
  private weights: StrategyWeights;

  constructor(store: MemoryStore, weights: Partial<StrategyWeights> = {}) {
    this.store = store;
    this.weights = {
      recency: weights.recency ?? 0.3,
      relevance: weights.relevance ?? 0.3,
      importance: weights.importance ?? 0.25,
      frequency: weights.frequency ?? 0.15,
    };
  }

  // ===========================================================================
  // RETRIEVAL
  // ===========================================================================

  /**
   * Retrieve memories matching a query.
   */
  async retrieve(
    query: string,
    options: Partial<RetrievalOptions> = {}
  ): Promise<RetrievalResult> {
    const startTime = performance.now();

    const opts: RetrievalOptions = {
      limit: options.limit ?? 10,
      strategy: options.strategy ?? 'hybrid',
      threshold: options.threshold ?? 0.3,
      types: options.types,
      tags: options.tags,
      timeRange: options.timeRange,
      applyDecay: options.applyDecay ?? true,
    };

    // Get all memories (filtered by type/tags)
    const memories = await this.store.query({
      type: opts.types?.[0],
      tags: opts.tags,
      after: opts.timeRange?.start,
      before: opts.timeRange?.end,
    });

    // Score each memory
    const scored = memories.map((memory) =>
      this.scoreMemory(memory, query, opts)
    );

    // Filter by threshold
    const filtered = scored.filter((s) => s.score >= opts.threshold!);

    // Sort by strategy
    const sorted = this.sortByStrategy(filtered, opts.strategy);

    // Apply limit
    const limited = sorted.slice(0, opts.limit);

    return {
      memories: limited,
      query,
      strategy: opts.strategy,
      totalSearched: memories.length,
      durationMs: performance.now() - startTime,
    };
  }

  /**
   * Retrieve memories similar to a given memory.
   */
  async retrieveSimilar(
    memoryId: string,
    limit = 5
  ): Promise<ScoredMemory[]> {
    const memory = await this.store.get(memoryId);
    if (!memory) return [];

    // Use memory content as query
    return (await this.retrieve(memory.content, { limit, strategy: 'relevance' })).memories;
  }

  /**
   * Retrieve the most important memories.
   */
  async retrieveImportant(limit = 10): Promise<ScoredMemory[]> {
    return (await this.retrieve('', { limit, strategy: 'importance' })).memories;
  }

  /**
   * Retrieve recent memories.
   */
  async retrieveRecent(limit = 10): Promise<ScoredMemory[]> {
    return (await this.retrieve('', { limit, strategy: 'recency' })).memories;
  }

  /**
   * Retrieve frequently accessed memories.
   */
  async retrieveFrequent(limit = 10): Promise<ScoredMemory[]> {
    return (await this.retrieve('', { limit, strategy: 'frequency' })).memories;
  }

  // ===========================================================================
  // SCORING
  // ===========================================================================

  /**
   * Score a memory against a query.
   */
  private scoreMemory(
    memory: MemoryEntry,
    query: string,
    options: RetrievalOptions
  ): ScoredMemory {
    const breakdown = {
      recency: this.calculateRecencyScore(memory),
      relevance: this.calculateRelevanceScore(memory, query),
      importance: this.calculateImportanceScore(memory, options.applyDecay),
      frequency: this.calculateFrequencyScore(memory),
    };

    // Calculate composite score based on strategy
    const score = this.calculateCompositeScore(breakdown, options.strategy);

    return {
      memory,
      score,
      scoreBreakdown: breakdown,
    };
  }

  /**
   * Calculate recency score (0-1).
   * More recent = higher score.
   */
  private calculateRecencyScore(memory: MemoryEntry): number {
    const now = Date.now();
    const lastAccess = memory.lastAccessed.getTime();
    const created = memory.createdAt.getTime();

    // Use the more recent of lastAccessed or created
    const relevantTime = Math.max(lastAccess, created);

    // Decay over time (half-life of 24 hours)
    const hoursSince = (now - relevantTime) / (1000 * 60 * 60);
    const halfLife = 24;

    return Math.pow(0.5, hoursSince / halfLife);
  }

  /**
   * Calculate relevance score (0-1).
   * Higher overlap with query = higher score.
   */
  private calculateRelevanceScore(memory: MemoryEntry, query: string): number {
    if (!query) return 0.5; // Neutral if no query

    // Simple word overlap similarity
    const queryWords = new Set(
      query.toLowerCase().split(/\W+/).filter((w) => w.length > 2)
    );
    const contentWords = new Set(
      memory.content.toLowerCase().split(/\W+/).filter((w) => w.length > 2)
    );
    const tagWords = new Set(memory.tags.map((t) => t.toLowerCase()));

    if (queryWords.size === 0) return 0.5;

    // Check content overlap
    let contentMatches = 0;
    for (const word of queryWords) {
      if (contentWords.has(word)) contentMatches++;
    }

    // Check tag overlap (weighted higher)
    let tagMatches = 0;
    for (const word of queryWords) {
      if (tagWords.has(word)) tagMatches++;
    }

    // Combine scores
    const contentScore = contentMatches / queryWords.size;
    const tagScore = tagMatches > 0 ? Math.min(1, tagMatches * 0.3) : 0;

    return Math.min(1, contentScore * 0.7 + tagScore * 0.3);
  }

  /**
   * Calculate importance score (0-1).
   * Optionally applies decay.
   */
  private calculateImportanceScore(
    memory: MemoryEntry,
    applyDecay = true
  ): number {
    let importance = memory.importance;

    if (applyDecay) {
      // Apply decay based on time since last access
      const hoursSince = (Date.now() - memory.lastAccessed.getTime()) / (1000 * 60 * 60);
      const decayFactor = Math.pow(memory.decayRate, hoursSince / 24);
      importance *= decayFactor;
    }

    return Math.max(0, Math.min(1, importance));
  }

  /**
   * Calculate frequency score (0-1).
   * More access = higher score (with diminishing returns).
   */
  private calculateFrequencyScore(memory: MemoryEntry): number {
    // Use log scale for diminishing returns
    // accessCount of 10 → ~0.7, 100 → ~0.85, 1000 → ~0.95
    return Math.min(1, Math.log10(memory.accessCount + 1) / 3);
  }

  /**
   * Calculate composite score based on strategy.
   *
   * USER CONTRIBUTION OPPORTUNITY:
   * Implement the hybrid strategy weighting.
   * Consider:
   * - Different weights for different contexts
   * - Adaptive weights based on query type
   * - Learning optimal weights from feedback
   */
  private calculateCompositeScore(
    breakdown: ScoredMemory['scoreBreakdown'],
    strategy: RetrievalStrategy
  ): number {
    switch (strategy) {
      case 'recency':
        return breakdown.recency;

      case 'relevance':
        return breakdown.relevance;

      case 'importance':
        return breakdown.importance;

      case 'frequency':
        return breakdown.frequency;

      case 'hybrid':
        // Weighted combination of all factors
        return (
          breakdown.recency * this.weights.recency +
          breakdown.relevance * this.weights.relevance +
          breakdown.importance * this.weights.importance +
          breakdown.frequency * this.weights.frequency
        );

      default:
        return breakdown.relevance;
    }
  }

  // ===========================================================================
  // SORTING
  // ===========================================================================

  /**
   * Sort scored memories by strategy.
   */
  private sortByStrategy(
    memories: ScoredMemory[],
    strategy: RetrievalStrategy
  ): ScoredMemory[] {
    return [...memories].sort((a, b) => {
      // Primary sort by composite score
      if (b.score !== a.score) {
        return b.score - a.score;
      }

      // Secondary sort based on strategy
      switch (strategy) {
        case 'recency':
          return b.scoreBreakdown.recency - a.scoreBreakdown.recency;
        case 'importance':
          return b.scoreBreakdown.importance - a.scoreBreakdown.importance;
        case 'frequency':
          return b.scoreBreakdown.frequency - a.scoreBreakdown.frequency;
        default:
          return b.scoreBreakdown.relevance - a.scoreBreakdown.relevance;
      }
    });
  }

  // ===========================================================================
  // CONFIGURATION
  // ===========================================================================

  /**
   * Update retrieval weights.
   */
  setWeights(weights: Partial<StrategyWeights>): void {
    if (weights.recency !== undefined) this.weights.recency = weights.recency;
    if (weights.relevance !== undefined) this.weights.relevance = weights.relevance;
    if (weights.importance !== undefined) this.weights.importance = weights.importance;
    if (weights.frequency !== undefined) this.weights.frequency = weights.frequency;

    // Normalize weights to sum to 1
    const total = this.weights.recency + this.weights.relevance +
                  this.weights.importance + this.weights.frequency;

    if (total > 0) {
      this.weights.recency /= total;
      this.weights.relevance /= total;
      this.weights.importance /= total;
      this.weights.frequency /= total;
    }
  }

  /**
   * Get current weights.
   */
  getWeights(): StrategyWeights {
    return { ...this.weights };
  }
}

// =============================================================================
// TYPES
// =============================================================================

/**
 * Weights for hybrid retrieval strategy.
 */
export interface StrategyWeights {
  recency: number;
  relevance: number;
  importance: number;
  frequency: number;
}

// =============================================================================
// SPECIALIZED RETRIEVERS
// =============================================================================

/**
 * Recency-focused retriever (for recent context).
 */
export function createRecencyRetriever(store: MemoryStore): MemoryRetriever {
  return new MemoryRetriever(store, {
    recency: 0.6,
    relevance: 0.2,
    importance: 0.15,
    frequency: 0.05,
  });
}

/**
 * Relevance-focused retriever (for search).
 */
export function createRelevanceRetriever(store: MemoryStore): MemoryRetriever {
  return new MemoryRetriever(store, {
    recency: 0.1,
    relevance: 0.6,
    importance: 0.2,
    frequency: 0.1,
  });
}

/**
 * Importance-focused retriever (for key facts).
 */
export function createImportanceRetriever(store: MemoryStore): MemoryRetriever {
  return new MemoryRetriever(store, {
    recency: 0.1,
    relevance: 0.2,
    importance: 0.6,
    frequency: 0.1,
  });
}

// =============================================================================
// EXPORTS
// =============================================================================

export function createRetriever(
  store: MemoryStore,
  weights?: Partial<StrategyWeights>
): MemoryRetriever {
  return new MemoryRetriever(store, weights);
}
