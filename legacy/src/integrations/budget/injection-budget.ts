/**
 * Injection Budget Manager
 *
 * Limits total context injections per iteration to prevent
 * injection overhead from overwhelming the actual conversation.
 *
 * Each injection type gets a priority and max token allocation.
 * Lower-priority injections are dropped when the budget is exhausted.
 *
 * Priority levels (lower = higher priority):
 * 0 - Critical: budget warnings, hard stops
 * 1 - High: doom loop detection
 * 2 - Medium: failure context, learning
 * 3 - Low: goal recitation
 * 4 - Lowest: exploration nudges
 */

import { estimateTokenCount } from '../utilities/token-estimate.js';

// =============================================================================
// TYPES
// =============================================================================

export interface InjectionSlot {
  /** Identifier for this injection */
  name: string;
  /** Priority (lower = higher priority, 0 = critical) */
  priority: number;
  /** Maximum tokens this injection can use */
  maxTokens: number;
  /** The content to inject */
  content: string;
}

export interface InjectionBudgetConfig {
  /** Max total tokens for all injections per iteration */
  maxTotalTokens: number;
  /** Named slot priorities (lower = higher priority) */
  slotPriorities: Record<string, number>;
}

export interface InjectionBudgetStats {
  /** Total proposed tokens */
  proposedTokens: number;
  /** Total accepted tokens */
  acceptedTokens: number;
  /** Number of proposals dropped */
  droppedCount: number;
  /** Number of proposals truncated */
  truncatedCount: number;
  /** Names of dropped injections */
  droppedNames: string[];
}

// =============================================================================
// CONSTANTS
// =============================================================================

const DEFAULT_CONFIG: InjectionBudgetConfig = {
  maxTotalTokens: 1500,
  slotPriorities: {
    budget_warning: 0,
    timeout_wrapup: 0,
    doom_loop: 1,
    failure_context: 2,
    learning_context: 2,
    recitation: 3,
    exploration_nudge: 4,
    phase_guidance: 4,
  },
};

// =============================================================================
// MANAGER
// =============================================================================

export class InjectionBudgetManager {
  private config: InjectionBudgetConfig;
  private lastStats: InjectionBudgetStats | null = null;

  constructor(config?: Partial<InjectionBudgetConfig>) {
    this.config = {
      maxTotalTokens: config?.maxTotalTokens ?? DEFAULT_CONFIG.maxTotalTokens,
      slotPriorities: {
        ...DEFAULT_CONFIG.slotPriorities,
        ...config?.slotPriorities,
      },
    };
  }

  /**
   * Given a set of proposed injections, return the ones that fit
   * within the budget, ordered by priority.
   */
  allocate(proposals: InjectionSlot[]): InjectionSlot[] {
    if (proposals.length === 0) return [];

    // Assign priorities from config for known slots
    const withPriority = proposals.map((slot) => ({
      ...slot,
      priority: this.config.slotPriorities[slot.name] ?? slot.priority,
    }));

    // Sort by priority (lower number = higher priority)
    const sorted = [...withPriority].sort((a, b) => a.priority - b.priority);

    const accepted: InjectionSlot[] = [];
    let remainingTokens = this.config.maxTotalTokens;
    let droppedCount = 0;
    let truncatedCount = 0;
    const droppedNames: string[] = [];
    let proposedTokens = 0;

    for (const slot of sorted) {
      const estimatedTokens = estimateTokens(slot.content);
      proposedTokens += estimatedTokens;
      const capped = Math.min(estimatedTokens, slot.maxTokens);

      if (capped <= remainingTokens) {
        // Fits within budget
        accepted.push(slot);
        remainingTokens -= capped;
      } else if (remainingTokens > 100) {
        // Partially fits — truncate content to fit
        const truncatedChars = remainingTokens * 4; // ~4 chars per token
        accepted.push({
          ...slot,
          content: slot.content.slice(0, truncatedChars) + '\n...(truncated for context budget)',
        });
        truncatedCount++;
        remainingTokens = 0;
      } else {
        // No budget remaining — drop
        droppedCount++;
        droppedNames.push(slot.name);
      }
    }

    this.lastStats = {
      proposedTokens,
      acceptedTokens: this.config.maxTotalTokens - remainingTokens,
      droppedCount,
      truncatedCount,
      droppedNames,
    };

    return accepted;
  }

  /**
   * Get stats from the last allocation.
   */
  getLastStats(): InjectionBudgetStats | null {
    return this.lastStats;
  }

  /**
   * Get priority for a named injection slot.
   */
  getPriority(name: string): number {
    return this.config.slotPriorities[name] ?? 5;
  }

  /**
   * Update the total token budget.
   */
  setMaxTokens(maxTokens: number): void {
    this.config.maxTotalTokens = maxTokens;
  }
}

// =============================================================================
// HELPERS
// =============================================================================

/**
 * Estimate token count from a string.
 */
function estimateTokens(text: string): number {
  return estimateTokenCount(text);
}

/**
 * Create an injection budget manager with optional config.
 */
export function createInjectionBudgetManager(
  config?: Partial<InjectionBudgetConfig>,
): InjectionBudgetManager {
  return new InjectionBudgetManager(config);
}
