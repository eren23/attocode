/**
 * Semantic Cache Integration
 *
 * Caches LLM responses based on semantic similarity of queries.
 * Returns cached response if a query is similar enough to a previous one.
 * Adapted from tricks/semantic-cache.ts.
 *
 * Usage:
 *   const cache = createSemanticCacheManager({ threshold: 0.95 });
 *   const hit = await cache.get("What is X?");
 *   if (hit) return hit.response;
 *   // else call LLM and cache result
 *   await cache.set("What is X?", response);
 */

// =============================================================================
// TYPES
// =============================================================================

/**
 * Cache entry.
 */
export interface CacheEntry {
  id: string;
  query: string;
  response: string;
  embedding?: number[];
  createdAt: Date;
  expiresAt?: Date;
  hitCount: number;
  metadata?: Record<string, unknown>;
}

/**
 * Cache hit result.
 */
export interface CacheHit {
  entry: CacheEntry;
  similarity: number;
}

/**
 * Embedding function type.
 */
export type EmbeddingFunction = (text: string) => Promise<number[]>;

/**
 * Semantic cache configuration.
 */
export interface SemanticCacheConfig {
  /** Enable/disable semantic caching */
  enabled?: boolean;
  /** Similarity threshold (0-1, default 0.95) - higher = more strict */
  threshold?: number;
  /** Maximum cache size (entries) */
  maxSize?: number;
  /** Time-to-live in milliseconds (0 = no expiry) */
  ttl?: number;
  /** Custom embedding function (uses simple hash-based by default) */
  embedFunction?: EmbeddingFunction;
}

/**
 * Cache statistics.
 */
export interface CacheStats {
  size: number;
  totalHits: number;
  avgHits: number;
  hitRate: number;
  totalQueries: number;
}

/**
 * Cache event types.
 */
export type CacheEvent =
  | { type: 'cache.hit'; query: string; similarity: number; entryId: string }
  | { type: 'cache.miss'; query: string }
  | { type: 'cache.set'; query: string; entryId: string }
  | { type: 'cache.evict'; entryId: string; reason: 'size' | 'ttl' }
  | { type: 'cache.cleared' };

export type CacheEventListener = (event: CacheEvent) => void;

// =============================================================================
// EMBEDDING UTILITIES
// =============================================================================

/**
 * Simple word-based embedding (for demo purposes).
 * Production should use real embedding model (OpenAI, Sentence Transformers, etc.)
 */
async function simpleEmbed(text: string): Promise<number[]> {
  // Normalize text
  const normalized = text.toLowerCase().replace(/[^\w\s]/g, '');
  const words = normalized.split(/\s+/);

  // Create a simple bag-of-words style embedding
  // Use a fixed vocabulary size with hashing
  const vocabSize = 256;
  const embedding = new Array(vocabSize).fill(0);

  for (const word of words) {
    const hash = simpleHash(word) % vocabSize;
    embedding[hash] += 1;
  }

  // Normalize
  const magnitude = Math.sqrt(embedding.reduce((sum, val) => sum + val * val, 0));
  if (magnitude > 0) {
    for (let i = 0; i < embedding.length; i++) {
      embedding[i] /= magnitude;
    }
  }

  return embedding;
}

/**
 * Simple hash function.
 */
function simpleHash(str: string): number {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    const char = str.charCodeAt(i);
    hash = (hash << 5) - hash + char;
    hash = hash & hash; // Convert to 32-bit integer
  }
  return Math.abs(hash);
}

/**
 * Cosine similarity between two vectors.
 */
export function cosineSimilarity(a: number[], b: number[]): number {
  if (a.length !== b.length) {
    throw new Error('Vectors must have same length');
  }

  let dotProduct = 0;
  let magnitudeA = 0;
  let magnitudeB = 0;

  for (let i = 0; i < a.length; i++) {
    dotProduct += a[i] * b[i];
    magnitudeA += a[i] * a[i];
    magnitudeB += b[i] * b[i];
  }

  magnitudeA = Math.sqrt(magnitudeA);
  magnitudeB = Math.sqrt(magnitudeB);

  if (magnitudeA === 0 || magnitudeB === 0) {
    return 0;
  }

  return dotProduct / (magnitudeA * magnitudeB);
}

/**
 * Generate unique ID.
 */
function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

// =============================================================================
// SEMANTIC CACHE MANAGER
// =============================================================================

/**
 * Manages semantic caching of LLM responses.
 */
export class SemanticCacheManager {
  private entries: Map<string, CacheEntry> = new Map();
  private config: Required<Omit<SemanticCacheConfig, 'embedFunction'>> & {
    embedFunction: EmbeddingFunction;
  };
  private eventListeners: Set<CacheEventListener> = new Set();
  private totalQueries: number = 0;
  private totalHits: number = 0;

  constructor(config: SemanticCacheConfig = {}) {
    this.config = {
      enabled: config.enabled ?? true,
      threshold: config.threshold ?? 0.95,
      maxSize: config.maxSize ?? 1000,
      ttl: config.ttl ?? 0, // No expiry by default
      embedFunction: config.embedFunction ?? simpleEmbed,
    };
  }

  /**
   * Get cached response for a query.
   */
  async get(query: string, threshold?: number): Promise<CacheHit | null> {
    if (!this.config.enabled) return null;

    this.totalQueries++;
    const effectiveThreshold = threshold ?? this.config.threshold;
    const queryEmbedding = await this.config.embedFunction(query);

    // Clean expired entries
    this.cleanExpired();

    let bestMatch: CacheHit | null = null;
    let bestSimilarity = 0;

    for (const entry of this.entries.values()) {
      if (!entry.embedding) continue;

      const similarity = cosineSimilarity(queryEmbedding, entry.embedding);

      if (similarity >= effectiveThreshold && similarity > bestSimilarity) {
        bestSimilarity = similarity;
        bestMatch = { entry, similarity };
      }
    }

    if (bestMatch) {
      // Update hit count
      bestMatch.entry.hitCount++;
      this.totalHits++;
      this.emit({
        type: 'cache.hit',
        query,
        similarity: bestMatch.similarity,
        entryId: bestMatch.entry.id,
      });
    } else {
      this.emit({ type: 'cache.miss', query });
    }

    return bestMatch;
  }

  /**
   * Store a query/response pair.
   */
  async set(query: string, response: string, metadata?: Record<string, unknown>): Promise<string> {
    if (!this.config.enabled) return '';

    // Enforce max size with LRU eviction
    if (this.entries.size >= this.config.maxSize) {
      this.evictLRU();
    }

    const embedding = await this.config.embedFunction(query);
    const now = new Date();

    const entry: CacheEntry = {
      id: generateId(),
      query,
      response,
      embedding,
      createdAt: now,
      expiresAt: this.config.ttl ? new Date(now.getTime() + this.config.ttl) : undefined,
      hitCount: 0,
      metadata,
    };

    this.entries.set(entry.id, entry);
    this.emit({ type: 'cache.set', query, entryId: entry.id });

    return entry.id;
  }

  /**
   * Check if a similar query exists (without incrementing hit count).
   */
  async has(query: string, threshold?: number): Promise<boolean> {
    if (!this.config.enabled) return false;

    const effectiveThreshold = threshold ?? this.config.threshold;
    const queryEmbedding = await this.config.embedFunction(query);

    for (const entry of this.entries.values()) {
      if (!entry.embedding) continue;

      const similarity = cosineSimilarity(queryEmbedding, entry.embedding);
      if (similarity >= effectiveThreshold) {
        return true;
      }
    }

    return false;
  }

  /**
   * Delete an entry by ID.
   */
  delete(id: string): boolean {
    return this.entries.delete(id);
  }

  /**
   * Clear all entries.
   */
  clear(): void {
    this.entries.clear();
    this.emit({ type: 'cache.cleared' });
  }

  /**
   * Get cache statistics.
   */
  getStats(): CacheStats {
    let totalHitCount = 0;
    for (const entry of this.entries.values()) {
      totalHitCount += entry.hitCount;
    }

    return {
      size: this.entries.size,
      totalHits: this.totalHits,
      avgHits: this.entries.size > 0 ? totalHitCount / this.entries.size : 0,
      hitRate: this.totalQueries > 0 ? this.totalHits / this.totalQueries : 0,
      totalQueries: this.totalQueries,
    };
  }

  /**
   * Find similar entries (for debugging/inspection).
   */
  async findSimilar(query: string, limit: number = 5): Promise<CacheHit[]> {
    if (!this.config.enabled) return [];

    const queryEmbedding = await this.config.embedFunction(query);
    const results: CacheHit[] = [];

    for (const entry of this.entries.values()) {
      if (!entry.embedding) continue;

      const similarity = cosineSimilarity(queryEmbedding, entry.embedding);
      results.push({ entry, similarity });
    }

    return results.sort((a, b) => b.similarity - a.similarity).slice(0, limit);
  }

  /**
   * Get all entries (for debugging).
   */
  getAllEntries(): CacheEntry[] {
    return Array.from(this.entries.values());
  }

  /**
   * Update configuration.
   */
  setConfig(updates: Partial<SemanticCacheConfig>): void {
    if (updates.enabled !== undefined) this.config.enabled = updates.enabled;
    if (updates.threshold !== undefined) this.config.threshold = updates.threshold;
    if (updates.maxSize !== undefined) this.config.maxSize = updates.maxSize;
    if (updates.ttl !== undefined) this.config.ttl = updates.ttl;
    if (updates.embedFunction) this.config.embedFunction = updates.embedFunction;
  }

  /**
   * Get current configuration.
   */
  getConfig(): Omit<SemanticCacheConfig, 'embedFunction'> {
    return {
      enabled: this.config.enabled,
      threshold: this.config.threshold,
      maxSize: this.config.maxSize,
      ttl: this.config.ttl,
    };
  }

  /**
   * Subscribe to cache events.
   */
  subscribe(listener: CacheEventListener): () => void {
    this.eventListeners.add(listener);
    return () => this.eventListeners.delete(listener);
  }

  /**
   * Cleanup resources.
   */
  cleanup(): void {
    this.entries.clear();
    this.eventListeners.clear();
    this.totalQueries = 0;
    this.totalHits = 0;
  }

  // Internal methods

  /**
   * Clean expired entries.
   */
  private cleanExpired(): void {
    if (!this.config.ttl) return;

    const now = new Date();

    for (const [id, entry] of this.entries) {
      if (entry.expiresAt && entry.expiresAt < now) {
        this.entries.delete(id);
        this.emit({ type: 'cache.evict', entryId: id, reason: 'ttl' });
      }
    }
  }

  /**
   * Evict least recently used entry.
   */
  private evictLRU(): void {
    let oldest: CacheEntry | null = null;
    let oldestId: string | null = null;

    for (const [id, entry] of this.entries) {
      if (!oldest || entry.createdAt < oldest.createdAt) {
        oldest = entry;
        oldestId = id;
      }
    }

    if (oldestId) {
      this.entries.delete(oldestId);
      this.emit({ type: 'cache.evict', entryId: oldestId, reason: 'size' });
    }
  }

  /**
   * Emit a cache event.
   */
  private emit(event: CacheEvent): void {
    for (const listener of this.eventListeners) {
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
 * Create a semantic cache manager.
 */
export function createSemanticCacheManager(config?: SemanticCacheConfig): SemanticCacheManager {
  return new SemanticCacheManager(config);
}

/**
 * Create a strict cache (higher similarity threshold).
 */
export function createStrictCache(): SemanticCacheManager {
  return new SemanticCacheManager({
    enabled: true,
    threshold: 0.98,
    maxSize: 500,
    ttl: 3600000, // 1 hour
  });
}

/**
 * Create a lenient cache (lower similarity threshold).
 */
export function createLenientCache(): SemanticCacheManager {
  return new SemanticCacheManager({
    enabled: true,
    threshold: 0.85,
    maxSize: 2000,
    ttl: 0, // No expiry
  });
}

// =============================================================================
// WRAPPER UTILITY
// =============================================================================

/**
 * Create a cached wrapper around an LLM call function.
 */
export function withSemanticCache<T extends (...args: string[]) => Promise<string>>(
  fn: T,
  cache: SemanticCacheManager,
): T {
  return (async (...args: string[]) => {
    const query = args.join('\n');

    // Check cache
    const hit = await cache.get(query);
    if (hit) {
      return hit.entry.response;
    }

    // Call function
    const response = await fn(...args);

    // Cache result
    await cache.set(query, response);

    return response;
  }) as T;
}
