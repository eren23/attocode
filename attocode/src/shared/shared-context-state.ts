/**
 * Shared Context State
 *
 * Central failure tracker + reference pool shared across all swarm workers.
 * Workers plug into this via ContextEngineeringManager.setSharedState() so
 * they can learn from sibling failures and share compaction references.
 *
 * Reuses FailureTracker from failure-evidence.ts and Reference type from
 * reversible-compaction.ts — no new tracking logic, just shared state.
 */

import {
  FailureTracker,
  createFailureTracker,
  extractInsights,
  type FailureInput,
  type Failure,
} from '../tricks/failure-evidence.js';

import type { Reference } from '../tricks/reversible-compaction.js';

// =============================================================================
// TYPES
// =============================================================================

export interface SharedContextConfig {
  /** Maximum failures to track across all workers (default: 100) */
  maxFailures?: number;
  /** Maximum compaction references to keep (default: 200) */
  maxReferences?: number;
  /** Shared static prefix for KV-cache alignment */
  staticPrefix?: string;
}

// =============================================================================
// SHARED CONTEXT STATE
// =============================================================================

export class SharedContextState {
  private failureTracker: FailureTracker;
  private references: Map<string, Reference> = new Map();
  private maxReferences: number;
  private staticPrefix: string;

  constructor(config: SharedContextConfig = {}) {
    this.maxReferences = config.maxReferences ?? 200;
    this.staticPrefix = config.staticPrefix ?? '';

    this.failureTracker = createFailureTracker({
      maxFailures: config.maxFailures ?? 100,
      preserveStackTraces: true,
      detectRepeats: true,
      repeatWarningThreshold: 3,
    });
  }

  // ---------------------------------------------------------------------------
  // Failure tracking — workers call these, all workers see results
  // ---------------------------------------------------------------------------

  /**
   * Record a failure from a worker. The workerId is prefixed to the action
   * so cross-worker patterns become visible.
   */
  recordFailure(workerId: string, input: FailureInput): Failure {
    return this.failureTracker.recordFailure({
      ...input,
      action: `[${workerId}] ${input.action}`,
    });
  }

  /**
   * Get failure context formatted for LLM inclusion.
   */
  getFailureContext(maxFailures: number = 10): string {
    return this.failureTracker.getFailureContext({ maxFailures });
  }

  /**
   * Get actionable insights from cross-worker failures.
   */
  getFailureInsights(): string[] {
    return extractInsights(this.failureTracker.getUnresolvedFailures());
  }

  /**
   * Check if an action has failed recently (from any worker).
   */
  hasRecentFailure(action: string, withinMs: number = 60000): boolean {
    return this.failureTracker.hasRecentFailure(action, withinMs);
  }

  /**
   * Mark a failure as resolved.
   */
  resolveFailure(failureId: string): boolean {
    return this.failureTracker.resolveFailure(failureId);
  }

  /**
   * Get the underlying FailureTracker so per-worker ContextEngineeringManagers
   * can swap their local tracker for this shared one.
   */
  getFailureTracker(): FailureTracker {
    return this.failureTracker;
  }

  // ---------------------------------------------------------------------------
  // Reference pool — compaction references from all workers
  // ---------------------------------------------------------------------------

  /**
   * Add references from a worker's compaction pass.
   * Deduplicates by type:value key.
   */
  addReferences(refs: Reference[]): void {
    for (const ref of refs) {
      const key = `${ref.type}:${ref.value}`;
      if (!this.references.has(key)) {
        this.references.set(key, ref);
      }
    }

    // Enforce max references — evict oldest (first inserted)
    if (this.references.size > this.maxReferences) {
      const excess = this.references.size - this.maxReferences;
      const keys = this.references.keys();
      for (let i = 0; i < excess; i++) {
        const next = keys.next();
        if (!next.done) {
          this.references.delete(next.value);
        }
      }
    }
  }

  /**
   * Search references by query (case-insensitive substring match).
   */
  searchReferences(query: string): Reference[] {
    const lowerQuery = query.toLowerCase();
    return Array.from(this.references.values()).filter(
      (r) => r.value.toLowerCase().includes(lowerQuery),
    );
  }

  /**
   * Get all references.
   */
  getAllReferences(): Reference[] {
    return Array.from(this.references.values());
  }

  // ---------------------------------------------------------------------------
  // Cache prefix — frozen at construction
  // ---------------------------------------------------------------------------

  /**
   * Get the shared static prefix for KV-cache alignment.
   * All workers using the same prefix benefit from cache hits.
   */
  getStaticPrefix(): string {
    return this.staticPrefix;
  }

  // ---------------------------------------------------------------------------
  // Stats & cleanup
  // ---------------------------------------------------------------------------

  getStats(): { failures: number; references: number } {
    return {
      failures: this.failureTracker.getStats().total,
      references: this.references.size,
    };
  }

  clear(): void {
    this.failureTracker.clear();
    this.references.clear();
  }
}

// =============================================================================
// FACTORY
// =============================================================================

export function createSharedContextState(
  config?: SharedContextConfig,
): SharedContextState {
  return new SharedContextState(config);
}
