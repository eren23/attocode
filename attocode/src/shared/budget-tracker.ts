/**
 * Worker Budget Tracker (Phase 3.2 completion)
 *
 * Lightweight per-worker budget + doom-loop tracker that reports to
 * SharedEconomicsState for cross-worker doom loop aggregation.
 */

import { computeToolFingerprint } from '../integrations/budget/economics.js';
import type { SharedEconomicsState } from './shared-economics-state.js';

// =============================================================================
// TYPES
// =============================================================================

export interface WorkerBudgetConfig {
  workerId: string;
  maxTokens: number;
  maxIterations: number;
  doomLoopThreshold?: number; // default: 3
}

export interface WorkerBudgetCheckResult {
  canContinue: boolean;
  reason?: string;
  budgetType?: 'tokens' | 'iterations' | 'doom_loop';
}

interface ToolCallRecord {
  fingerprint: string;
  timestamp: number;
}

// =============================================================================
// WORKER BUDGET TRACKER
// =============================================================================

export class WorkerBudgetTracker {
  private workerId: string;
  private maxTokens: number;
  private maxIterations: number;
  private doomLoopThreshold: number;

  private inputTokens = 0;
  private outputTokens = 0;
  private iterations = 0;
  private toolCalls: ToolCallRecord[] = [];
  private sharedEconomics?: SharedEconomicsState;

  constructor(config: WorkerBudgetConfig, sharedEconomics?: SharedEconomicsState) {
    this.workerId = config.workerId;
    this.maxTokens = config.maxTokens;
    this.maxIterations = config.maxIterations;
    this.doomLoopThreshold = config.doomLoopThreshold ?? 3;
    this.sharedEconomics = sharedEconomics;
  }

  /**
   * Record LLM token usage.
   */
  recordLLMUsage(inputTokens: number, outputTokens: number): void {
    this.inputTokens += inputTokens;
    this.outputTokens += outputTokens;
  }

  /**
   * Record a completed iteration.
   */
  recordIteration(): void {
    this.iterations++;
  }

  /**
   * Record a tool call. Computes fingerprint and reports to SharedEconomicsState.
   */
  recordToolCall(toolName: string, args: string): void {
    const fingerprint = computeToolFingerprint(toolName, args);
    this.toolCalls.push({ fingerprint, timestamp: Date.now() });

    // Report to shared economics for cross-worker doom loop detection
    if (this.sharedEconomics) {
      this.sharedEconomics.recordToolCall(this.workerId, fingerprint);
    }
  }

  /**
   * Check if the worker can continue within budget.
   */
  checkBudget(): WorkerBudgetCheckResult {
    // Token budget
    const totalTokens = this.inputTokens + this.outputTokens;
    if (totalTokens >= this.maxTokens) {
      return {
        canContinue: false,
        reason: `Token budget exhausted: ${totalTokens.toLocaleString()} / ${this.maxTokens.toLocaleString()}`,
        budgetType: 'tokens',
      };
    }

    // Iteration budget
    if (this.iterations >= this.maxIterations) {
      return {
        canContinue: false,
        reason: `Iteration budget exhausted: ${this.iterations} / ${this.maxIterations}`,
        budgetType: 'iterations',
      };
    }

    // Local doom loop detection (consecutive identical tool calls)
    if (this.toolCalls.length >= this.doomLoopThreshold) {
      const recent = this.toolCalls.slice(-this.doomLoopThreshold);
      const allSame = recent.every((tc) => tc.fingerprint === recent[0].fingerprint);
      if (allSame) {
        return {
          canContinue: false,
          reason: `Doom loop detected: ${this.doomLoopThreshold} consecutive identical tool calls`,
          budgetType: 'doom_loop',
        };
      }
    }

    // Cross-worker doom loop detection via SharedEconomicsState
    if (this.sharedEconomics && this.toolCalls.length > 0) {
      const lastFingerprint = this.toolCalls[this.toolCalls.length - 1].fingerprint;
      if (this.sharedEconomics.isGlobalDoomLoop(lastFingerprint)) {
        const info = this.sharedEconomics.getGlobalLoopInfo(lastFingerprint);
        return {
          canContinue: false,
          reason: `Global doom loop: ${info?.count ?? 0} calls across ${info?.workerCount ?? 0} workers`,
          budgetType: 'doom_loop',
        };
      }
    }

    return { canContinue: true };
  }

  /**
   * Get current usage stats.
   */
  getUsage(): {
    inputTokens: number;
    outputTokens: number;
    totalTokens: number;
    iterations: number;
    toolCalls: number;
  } {
    return {
      inputTokens: this.inputTokens,
      outputTokens: this.outputTokens,
      totalTokens: this.inputTokens + this.outputTokens,
      iterations: this.iterations,
      toolCalls: this.toolCalls.length,
    };
  }

  /**
   * Get budget utilization as a percentage (0-100).
   */
  getUtilization(): { tokenPercent: number; iterationPercent: number } {
    const totalTokens = this.inputTokens + this.outputTokens;
    return {
      tokenPercent: this.maxTokens > 0 ? Math.round((totalTokens / this.maxTokens) * 100) : 0,
      iterationPercent:
        this.maxIterations > 0 ? Math.round((this.iterations / this.maxIterations) * 100) : 0,
    };
  }
}

// =============================================================================
// FACTORY
// =============================================================================

export function createWorkerBudgetTracker(
  config: WorkerBudgetConfig,
  sharedEconomics?: SharedEconomicsState,
): WorkerBudgetTracker {
  return new WorkerBudgetTracker(config, sharedEconomics);
}
