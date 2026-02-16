/**
 * Async Subagent Execution
 *
 * Provides non-blocking subagent spawning, returning a SubagentHandle
 * that the parent can monitor, steer, or cancel without blocking.
 *
 * This enables the parent coordinator to:
 * - Spawn multiple subagents and monitor them in a supervision loop
 * - Redirect stuck agents before they exhaust their timeout
 * - Cancel agents that are no longer needed (e.g., another found the answer)
 * - Collect partial results from agents that timed out
 *
 * Design: wraps existing spawn infrastructure with Promise-based handles.
 */

import type { SpawnResult } from './agent-registry.js';

// =============================================================================
// TYPES
// =============================================================================

export interface SubagentHandle {
  /** Unique handle ID */
  id: string;
  /** Agent name/type */
  agentName: string;
  /** Task description */
  task: string;
  /** Promise that resolves when the agent completes */
  completion: Promise<SpawnResult>;
  /** Whether the agent is still running */
  isRunning: () => boolean;
  /** Request graceful wrapup with optional reason */
  requestWrapup: (reason?: string) => void;
  /** Cancel the agent immediately */
  cancel: () => void;
  /** Get current progress info (if available) */
  getProgress: () => SubagentProgress;
  /** Register a progress callback */
  onProgress: (callback: ProgressCallback) => void;
  /** Time the agent was spawned */
  startedAt: number;
}

export interface SubagentProgress {
  /** Number of LLM iterations completed */
  iterations: number;
  /** Number of tool calls executed */
  toolCalls: number;
  /** Tokens consumed so far */
  tokensUsed: number;
  /** Current phase (if tracked) */
  phase?: string;
  /** Last tool called */
  lastTool?: string;
  /** Whether the agent has been asked to wrap up */
  wrapupRequested: boolean;
  /** Elapsed time in ms */
  elapsedMs: number;
}

export type ProgressCallback = (progress: SubagentProgress) => void;

export interface AsyncSubagentConfig {
  /** How often to poll for progress (default: 5000ms) */
  progressIntervalMs?: number;
  /** Maximum concurrent async agents (default: 5) */
  maxConcurrent?: number;
  /** Auto-wrapup if no progress in this many ms (default: 120000) */
  idleTimeoutMs?: number;
}

export interface SubagentSupervisorConfig {
  /** How often the supervisor checks agents (default: 10000ms) */
  checkIntervalMs?: number;
  /** Auto-cancel agents that exceed this duration (default: none) */
  maxDurationMs?: number;
  /** Auto-wrapup agents when total token usage exceeds this */
  tokenBudgetWrapup?: number;
}

// =============================================================================
// HANDLE FACTORY
// =============================================================================

/**
 * Create an async subagent handle that wraps a spawn operation.
 *
 * This is a handle-only pattern: the actual spawning is still done by
 * the parent's spawnAgent() method. This function wraps the promise
 * and provides the control interface.
 */
export function createSubagentHandle(
  id: string,
  agentName: string,
  task: string,
  spawnPromise: Promise<SpawnResult>,
  controls: {
    requestWrapup?: (reason?: string) => void;
    cancel?: () => void;
    getProgress?: () => SubagentProgress;
  },
): SubagentHandle {
  let running = true;
  let result: SpawnResult | undefined;
  const progressCallbacks: ProgressCallback[] = [];

  // Track completion
  const completion = spawnPromise.then(
    (res) => {
      running = false;
      result = res;
      return res;
    },
    (err) => {
      running = false;
      const failResult: SpawnResult = {
        success: false,
        output: err instanceof Error ? err.message : String(err),
        metrics: { tokens: 0, duration: Date.now() - startedAt, toolCalls: 0 },
      };
      result = failResult;
      return failResult;
    },
  );

  const startedAt = Date.now();

  const defaultProgress: SubagentProgress = {
    iterations: 0,
    toolCalls: 0,
    tokensUsed: 0,
    wrapupRequested: false,
    elapsedMs: 0,
  };

  return {
    id,
    agentName,
    task,
    completion,
    startedAt,
    isRunning: () => running,
    requestWrapup: (reason?: string) => {
      controls.requestWrapup?.(reason);
    },
    cancel: () => {
      controls.cancel?.();
    },
    getProgress: () => {
      if (!running && result) {
        return {
          iterations: 0,
          toolCalls: result.metrics.toolCalls,
          tokensUsed: result.metrics.tokens,
          wrapupRequested: false,
          elapsedMs: result.metrics.duration,
        };
      }
      const progress = controls.getProgress?.() ?? {
        ...defaultProgress,
        elapsedMs: Date.now() - startedAt,
      };
      return progress;
    },
    onProgress: (callback: ProgressCallback) => {
      progressCallbacks.push(callback);
    },
  };
}

// =============================================================================
// SUPERVISOR
// =============================================================================

/**
 * Supervise multiple async subagents.
 * Monitors progress and applies policies (idle timeout, token budget).
 */
export class SubagentSupervisor {
  private handles: Map<string, SubagentHandle> = new Map();
  private config: Required<SubagentSupervisorConfig>;
  private checkTimer: ReturnType<typeof setInterval> | null = null;

  constructor(config?: SubagentSupervisorConfig) {
    this.config = {
      checkIntervalMs: config?.checkIntervalMs ?? 10000,
      maxDurationMs: config?.maxDurationMs ?? 0,
      tokenBudgetWrapup: config?.tokenBudgetWrapup ?? 0,
    };
  }

  /**
   * Add a handle to supervise.
   */
  add(handle: SubagentHandle): void {
    this.handles.set(handle.id, handle);
    this.ensureChecking();
  }

  /**
   * Remove a handle from supervision.
   */
  remove(handleId: string): void {
    this.handles.delete(handleId);
    if (this.handles.size === 0) {
      this.stopChecking();
    }
  }

  /**
   * Get all active handles.
   */
  getActive(): SubagentHandle[] {
    return [...this.handles.values()].filter(h => h.isRunning());
  }

  /**
   * Get all completed handles.
   */
  getCompleted(): SubagentHandle[] {
    return [...this.handles.values()].filter(h => !h.isRunning());
  }

  /**
   * Wait for all handles to complete (or timeout).
   */
  async waitAll(timeoutMs?: number): Promise<SpawnResult[]> {
    const promises = [...this.handles.values()].map(h => h.completion);

    if (timeoutMs) {
      const timeout = new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error('Supervisor timeout')), timeoutMs),
      );
      return Promise.race([
        Promise.all(promises),
        timeout.then(() => [] as SpawnResult[]),
      ]);
    }

    return Promise.all(promises);
  }

  /**
   * Wait for any handle to complete. Returns the first completed result.
   */
  async waitAny(): Promise<{ handle: SubagentHandle; result: SpawnResult }> {
    const entries = [...this.handles.entries()];
    const racePromises = entries.map(([id, handle]) =>
      handle.completion.then(result => ({ id, handle, result })),
    );
    return Promise.race(racePromises);
  }

  /**
   * Cancel all running agents.
   */
  cancelAll(): void {
    for (const handle of this.handles.values()) {
      if (handle.isRunning()) {
        handle.cancel();
      }
    }
  }

  /**
   * Stop the supervisor check loop.
   */
  stop(): void {
    this.stopChecking();
    this.handles.clear();
  }

  // ===========================================================================
  // INTERNAL
  // ===========================================================================

  private ensureChecking(): void {
    if (this.checkTimer) return;
    this.checkTimer = setInterval(() => this.checkAgents(), this.config.checkIntervalMs);
  }

  private stopChecking(): void {
    if (this.checkTimer) {
      clearInterval(this.checkTimer);
      this.checkTimer = null;
    }
  }

  private checkAgents(): void {
    for (const [id, handle] of this.handles) {
      if (!handle.isRunning()) {
        // Auto-remove completed handles
        this.handles.delete(id);
        continue;
      }

      const progress = handle.getProgress();

      // Check max duration
      if (this.config.maxDurationMs > 0 && progress.elapsedMs > this.config.maxDurationMs) {
        handle.requestWrapup(`Duration exceeded ${this.config.maxDurationMs}ms`);
      }

      // Check token budget
      if (this.config.tokenBudgetWrapup > 0 && progress.tokensUsed > this.config.tokenBudgetWrapup) {
        handle.requestWrapup(`Token usage exceeded ${this.config.tokenBudgetWrapup}`);
      }
    }

    if (this.handles.size === 0) {
      this.stopChecking();
    }
  }
}

/**
 * Create a subagent supervisor.
 */
export function createSubagentSupervisor(
  config?: SubagentSupervisorConfig,
): SubagentSupervisor {
  return new SubagentSupervisor(config);
}
