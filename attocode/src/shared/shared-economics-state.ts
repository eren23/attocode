/**
 * Shared Economics State
 *
 * Cross-worker doom loop aggregation for swarm execution.
 * Detects when multiple workers are stuck on the same tool call pattern,
 * even though each worker's local doom loop detector only sees its own calls.
 *
 * Reuses computeToolFingerprint from economics.ts.
 */

// =============================================================================
// TYPES
// =============================================================================

export interface SharedEconomicsConfig {
  /** Threshold for global doom loop detection across all workers (default: 10) */
  globalDoomLoopThreshold?: number;
}

interface FingerprintEntry {
  count: number;
  workers: Set<string>;
}

// =============================================================================
// SHARED ECONOMICS STATE
// =============================================================================

export class SharedEconomicsState {
  private toolFingerprints: Map<string, FingerprintEntry> = new Map();
  private threshold: number;

  constructor(config?: SharedEconomicsConfig) {
    this.threshold = config?.globalDoomLoopThreshold ?? 10;
  }

  /**
   * Record a tool call fingerprint from a worker.
   * Called by per-worker ExecutionEconomicsManager.recordToolCall().
   */
  recordToolCall(workerId: string, fingerprint: string): void {
    let entry = this.toolFingerprints.get(fingerprint);
    if (!entry) {
      entry = { count: 0, workers: new Set() };
      this.toolFingerprints.set(fingerprint, entry);
    }
    entry.count++;
    entry.workers.add(workerId);
  }

  /**
   * Check if a tool fingerprint has exceeded the global doom loop threshold.
   */
  isGlobalDoomLoop(fingerprint: string): boolean {
    const entry = this.toolFingerprints.get(fingerprint);
    if (!entry) return false;
    return entry.count >= this.threshold;
  }

  /**
   * Get detailed info about a fingerprint's global usage.
   */
  getGlobalLoopInfo(
    fingerprint: string,
  ): { count: number; workerCount: number } | null {
    const entry = this.toolFingerprints.get(fingerprint);
    if (!entry) return null;
    return { count: entry.count, workerCount: entry.workers.size };
  }

  /**
   * Get all fingerprints that have exceeded the global threshold.
   */
  getGlobalLoops(): string[] {
    const loops: string[] = [];
    for (const [fingerprint, entry] of this.toolFingerprints) {
      if (entry.count >= this.threshold) {
        loops.push(fingerprint);
      }
    }
    return loops;
  }

  getStats(): { fingerprints: number; globalLoops: string[] } {
    return {
      fingerprints: this.toolFingerprints.size,
      globalLoops: this.getGlobalLoops(),
    };
  }

  clear(): void {
    this.toolFingerprints.clear();
  }
}

// =============================================================================
// FACTORY
// =============================================================================

export function createSharedEconomicsState(
  config?: SharedEconomicsConfig,
): SharedEconomicsState {
  return new SharedEconomicsState(config);
}
