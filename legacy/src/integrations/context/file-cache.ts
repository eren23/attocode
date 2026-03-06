/**
 * Shared File Cache
 *
 * Provides an in-memory LRU file cache shared across parent and child agents.
 * Eliminates redundant file reads in multi-agent workflows where parent + N children
 * each independently read the same large files (e.g., agent.ts at 212KB).
 *
 * The cache is created by the parent agent and passed to subagents via config.
 * Since subagents run in the same process, they share the same Map reference.
 *
 * Cache invalidation:
 * - Write operations to a file invalidate its cache entry
 * - Entries expire after a configurable TTL (default: 5 minutes)
 * - LRU eviction when max cache size is exceeded
 *
 * All file paths are normalized via path.resolve() to ensure consistent cache
 * keys regardless of relative vs absolute path usage across agents.
 */

import { resolve } from 'node:path';
import type { TraceCollector } from '../../tracing/trace-collector.js';

// =============================================================================
// TYPES
// =============================================================================

export interface FileCacheEntry {
  content: string;
  timestamp: number;
  size: number;
  /** How many times this entry has been served from cache */
  hits: number;
}

export interface FileCacheConfig {
  /** Maximum total cache size in bytes (default: 5MB) */
  maxCacheBytes?: number;
  /** Time-to-live for cache entries in ms (default: 5 minutes) */
  ttlMs?: number;
  /** Whether to enable cache statistics tracking */
  trackStats?: boolean;
  /** Optional trace collector for emitting filecache.event trace events */
  traceCollector?: TraceCollector;
  /** Agent ID to include in trace events */
  agentId?: string;
}

export interface FileCacheStats {
  /** Total cache hits */
  hits: number;
  /** Total cache misses */
  misses: number;
  /** Total invalidations (from writes) */
  invalidations: number;
  /** Total evictions (from LRU) */
  evictions: number;
  /** Current number of entries */
  entries: number;
  /** Current cache size in bytes */
  currentBytes: number;
  /** Hit rate (0-1) */
  hitRate: number;
}

// =============================================================================
// SHARED FILE CACHE
// =============================================================================

export class SharedFileCache {
  private cache = new Map<string, FileCacheEntry>();
  private accessOrder: string[] = []; // LRU tracking (most recent at end)
  private currentBytes = 0;

  private readonly maxCacheBytes: number;
  private readonly ttlMs: number;
  private readonly trackStats: boolean;
  private readonly traceCollector?: TraceCollector;
  private readonly agentId?: string;

  // Statistics
  private hits = 0;
  private misses = 0;
  private invalidations = 0;
  private evictions = 0;

  constructor(config: FileCacheConfig = {}) {
    this.maxCacheBytes = config.maxCacheBytes ?? 5 * 1024 * 1024; // 5MB
    this.ttlMs = config.ttlMs ?? 5 * 60 * 1000; // 5 minutes
    this.trackStats = config.trackStats ?? true;
    this.traceCollector = config.traceCollector;
    this.agentId = config.agentId;
  }

  /** Normalize path to ensure consistent cache keys across agents */
  private normalizePath(filePath: string): string {
    return resolve(filePath);
  }

  /**
   * Get a file's content from cache.
   * Returns undefined if not cached, expired, or evicted.
   */
  get(filePath: string): string | undefined {
    filePath = this.normalizePath(filePath);
    const entry = this.cache.get(filePath);

    if (!entry) {
      if (this.trackStats) this.misses++;
      this.traceCollector?.record({
        type: 'filecache.event',
        data: {
          action: 'miss',
          filePath,
          agentId: this.agentId,
          currentEntries: this.cache.size,
          currentBytes: this.currentBytes,
        },
      });
      return undefined;
    }

    // Check TTL
    if (Date.now() - entry.timestamp > this.ttlMs) {
      this.delete(filePath);
      if (this.trackStats) this.misses++;
      this.traceCollector?.record({
        type: 'filecache.event',
        data: {
          action: 'miss',
          filePath,
          agentId: this.agentId,
          currentEntries: this.cache.size,
          currentBytes: this.currentBytes,
        },
      });
      return undefined;
    }

    // Update LRU order
    this.touchLRU(filePath);

    // Track hit
    entry.hits++;
    if (this.trackStats) this.hits++;

    this.traceCollector?.record({
      type: 'filecache.event',
      data: {
        action: 'hit',
        filePath,
        agentId: this.agentId,
        currentEntries: this.cache.size,
        currentBytes: this.currentBytes,
      },
    });

    return entry.content;
  }

  /**
   * Store a file's content in cache.
   * Evicts LRU entries if needed to make room.
   */
  set(filePath: string, content: string): void {
    filePath = this.normalizePath(filePath);
    const size = content.length;

    // Don't cache files larger than 50% of max cache size
    if (size > this.maxCacheBytes * 0.5) {
      return;
    }

    // Remove existing entry if present (to update)
    if (this.cache.has(filePath)) {
      this.delete(filePath);
    }

    // Evict LRU entries until there's room
    while (this.currentBytes + size > this.maxCacheBytes && this.accessOrder.length > 0) {
      const lruPath = this.accessOrder[0];
      this.delete(lruPath);
      if (this.trackStats) this.evictions++;
    }

    // Store entry
    this.cache.set(filePath, {
      content,
      timestamp: Date.now(),
      size,
      hits: 0,
    });
    this.currentBytes += size;
    this.accessOrder.push(filePath);

    this.traceCollector?.record({
      type: 'filecache.event',
      data: {
        action: 'set',
        filePath,
        agentId: this.agentId,
        currentEntries: this.cache.size,
        currentBytes: this.currentBytes,
      },
    });
  }

  /**
   * Invalidate a cache entry (called when a file is written/modified).
   */
  invalidate(filePath: string): void {
    filePath = this.normalizePath(filePath);
    if (this.cache.has(filePath)) {
      this.delete(filePath);
      if (this.trackStats) this.invalidations++;
      this.traceCollector?.record({
        type: 'filecache.event',
        data: {
          action: 'invalidate',
          filePath,
          agentId: this.agentId,
          currentEntries: this.cache.size,
          currentBytes: this.currentBytes,
        },
      });
    }
  }

  /**
   * Get cache statistics.
   */
  getStats(): FileCacheStats {
    const total = this.hits + this.misses;
    return {
      hits: this.hits,
      misses: this.misses,
      invalidations: this.invalidations,
      evictions: this.evictions,
      entries: this.cache.size,
      currentBytes: this.currentBytes,
      hitRate: total > 0 ? this.hits / total : 0,
    };
  }

  /**
   * Clear all cache entries.
   */
  clear(): void {
    this.cache.clear();
    this.accessOrder = [];
    this.currentBytes = 0;
  }

  // Internal: delete an entry and update bookkeeping
  private delete(filePath: string): void {
    const entry = this.cache.get(filePath);
    if (entry) {
      this.currentBytes -= entry.size;
      this.cache.delete(filePath);
    }
    const idx = this.accessOrder.indexOf(filePath);
    if (idx !== -1) {
      this.accessOrder.splice(idx, 1);
    }
  }

  // Internal: move entry to end of LRU list (most recently used)
  private touchLRU(filePath: string): void {
    const idx = this.accessOrder.indexOf(filePath);
    if (idx !== -1) {
      this.accessOrder.splice(idx, 1);
    }
    this.accessOrder.push(filePath);
  }
}

// =============================================================================
// FACTORY
// =============================================================================

export function createSharedFileCache(config?: FileCacheConfig): SharedFileCache {
  return new SharedFileCache(config);
}
