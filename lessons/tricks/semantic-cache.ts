/**
 * Trick F: Semantic Caching
 *
 * Cache LLM responses based on semantic similarity.
 * Returns cached response if query is similar enough to a previous one.
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
 * Cache options.
 */
export interface CacheOptions {
  /** Similarity threshold (0-1, default 0.95) */
  threshold?: number;
  /** Maximum cache size */
  maxSize?: number;
  /** Time-to-live in milliseconds */
  ttl?: number;
  /** Embedding function */
  embed?: EmbeddingFunction;
}

// =============================================================================
// SEMANTIC CACHE
// =============================================================================

/**
 * Semantic cache for LLM responses.
 */
export class SemanticCache {
  private entries: Map<string, CacheEntry> = new Map();
  private threshold: number;
  private maxSize: number;
  private ttl?: number;
  private embed: EmbeddingFunction;

  constructor(options: CacheOptions = {}) {
    this.threshold = options.threshold ?? 0.95;
    this.maxSize = options.maxSize ?? 1000;
    this.ttl = options.ttl;
    this.embed = options.embed ?? simpleEmbed;
  }

  /**
   * Get cached response for a query.
   */
  async get(query: string, threshold?: number): Promise<CacheHit | null> {
    const effectiveThreshold = threshold ?? this.threshold;
    const queryEmbedding = await this.embed(query);

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
    }

    return bestMatch;
  }

  /**
   * Store a query/response pair.
   */
  async set(query: string, response: string, metadata?: Record<string, unknown>): Promise<void> {
    // Enforce max size with LRU eviction
    if (this.entries.size >= this.maxSize) {
      this.evictLRU();
    }

    const embedding = await this.embed(query);
    const now = new Date();

    const entry: CacheEntry = {
      id: generateId(),
      query,
      response,
      embedding,
      createdAt: now,
      expiresAt: this.ttl ? new Date(now.getTime() + this.ttl) : undefined,
      hitCount: 0,
      metadata,
    };

    this.entries.set(entry.id, entry);
  }

  /**
   * Check if a similar query exists (without incrementing hit count).
   */
  async has(query: string, threshold?: number): Promise<boolean> {
    const effectiveThreshold = threshold ?? this.threshold;
    const queryEmbedding = await this.embed(query);

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
   * Delete an entry.
   */
  delete(id: string): boolean {
    return this.entries.delete(id);
  }

  /**
   * Clear all entries.
   */
  clear(): void {
    this.entries.clear();
  }

  /**
   * Get cache statistics.
   */
  stats(): { size: number; totalHits: number; avgHits: number } {
    let totalHits = 0;
    for (const entry of this.entries.values()) {
      totalHits += entry.hitCount;
    }

    return {
      size: this.entries.size,
      totalHits,
      avgHits: this.entries.size > 0 ? totalHits / this.entries.size : 0,
    };
  }

  /**
   * Find similar entries (for debugging/inspection).
   */
  async findSimilar(query: string, limit: number = 5): Promise<CacheHit[]> {
    const queryEmbedding = await this.embed(query);
    const results: CacheHit[] = [];

    for (const entry of this.entries.values()) {
      if (!entry.embedding) continue;

      const similarity = cosineSimilarity(queryEmbedding, entry.embedding);
      results.push({ entry, similarity });
    }

    return results.sort((a, b) => b.similarity - a.similarity).slice(0, limit);
  }

  /**
   * Clean expired entries.
   */
  private cleanExpired(): void {
    const now = new Date();

    for (const [id, entry] of this.entries) {
      if (entry.expiresAt && entry.expiresAt < now) {
        this.entries.delete(id);
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
    }
  }
}

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

// =============================================================================
// UTILITIES
// =============================================================================

/**
 * Generate unique ID.
 */
function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

/**
 * Create a cached LLM wrapper.
 */
export function withCache<T extends (...args: string[]) => Promise<string>>(
  fn: T,
  cache: SemanticCache
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

// =============================================================================
// EXPORTS
// =============================================================================

export function createSemanticCache(options?: CacheOptions): SemanticCache {
  return new SemanticCache(options);
}

// Usage:
// const cache = createSemanticCache({ threshold: 0.9, maxSize: 1000, ttl: 3600000 });
//
// // Check cache
// const hit = await cache.get("What is the capital of France?");
// if (hit) {
//   console.log(`Cache hit (${hit.similarity}): ${hit.entry.response}`);
// } else {
//   const response = await llm.generate("What is the capital of France?");
//   await cache.set("What is the capital of France?", response);
// }
//
// // Or use wrapper
// const cachedLLM = withCache(llm.generate.bind(llm), cache);
// const response = await cachedLLM("What is the capital of France?");
