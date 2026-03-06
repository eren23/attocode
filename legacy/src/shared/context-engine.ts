/**
 * Shared Context Engine (Phase 3.1)
 *
 * Orchestration layer that composes SharedContextState primitives into
 * worker-optimized prompts. Workers get a single buildWorkerSystemPrompt()
 * call instead of manually assembling prefix + failures + recitation.
 */

import type { SharedContextState } from './shared-context-state.js';
import type { FailureInput, Failure } from '../tricks/failure-evidence.js';
import type { Reference } from '../tricks/reversible-compaction.js';

// =============================================================================
// TYPES
// =============================================================================

export interface SharedContextEngineConfig {
  /** Maximum failures to include in worker prompts (default: 5) */
  maxFailuresInPrompt?: number;
  /** Whether to include cross-worker insights (default: true) */
  includeInsights?: boolean;
}

export interface WorkerTask {
  /** Unique task ID */
  id: string;
  /** Human-readable task description */
  description: string;
  /** The specific goal this worker should accomplish */
  goal: string;
  /** IDs of tasks this depends on */
  dependencies?: string[];
  /** Additional context for this specific task */
  context?: string;
}

// =============================================================================
// SHARED CONTEXT ENGINE
// =============================================================================

export class SharedContextEngine {
  private contextState: SharedContextState;
  private maxFailuresInPrompt: number;
  private includeInsights: boolean;

  constructor(contextState: SharedContextState, config: SharedContextEngineConfig = {}) {
    this.contextState = contextState;
    this.maxFailuresInPrompt = config.maxFailuresInPrompt ?? 5;
    this.includeInsights = config.includeInsights ?? true;
  }

  /**
   * Build a complete system prompt for a worker.
   * Concatenates: shared prefix → task context → failure guidance → goal recitation.
   * Empty sections are omitted.
   */
  buildWorkerSystemPrompt(task: WorkerTask): string {
    const sections: string[] = [];

    // 1. Shared prefix (cache-aligned, identical for all workers)
    const prefix = this.getSharedPrefix();
    if (prefix) {
      sections.push(prefix);
    }

    // 2. Task context
    const taskSection = this.buildTaskSection(task);
    if (taskSection) {
      sections.push(taskSection);
    }

    // 3. Failure guidance
    const failureGuidance = this.getFailureGuidance();
    if (failureGuidance) {
      sections.push(failureGuidance);
    }

    // 4. Goal recitation
    const goalRecitation = this.getGoalRecitation(task);
    if (goalRecitation) {
      sections.push(goalRecitation);
    }

    return sections.join('\n\n');
  }

  /**
   * Get the shared static prefix for KV-cache alignment.
   */
  getSharedPrefix(): string {
    return this.contextState.getStaticPrefix();
  }

  /**
   * Report a failure from a worker. Delegates to SharedContextState.
   */
  reportFailure(workerId: string, failure: FailureInput): Failure {
    return this.contextState.recordFailure(workerId, failure);
  }

  /**
   * Get formatted failure guidance for inclusion in prompts.
   * Returns empty string when no failures exist.
   */
  getFailureGuidance(): string {
    const parts: string[] = [];

    const failureContext = this.contextState.getFailureContext(this.maxFailuresInPrompt);
    if (failureContext) {
      parts.push(failureContext);
    }

    if (this.includeInsights) {
      const insights = this.contextState.getFailureInsights();
      if (insights.length > 0) {
        parts.push('## Cross-Worker Insights\n' + insights.map((i) => `- ${i}`).join('\n'));
      }
    }

    return parts.join('\n\n');
  }

  /**
   * Get a goal recitation block for a worker task.
   */
  getGoalRecitation(task: WorkerTask): string {
    const lines: string[] = [
      '## Current Goal',
      `**Task:** ${task.description}`,
      `**Goal:** ${task.goal}`,
    ];

    if (task.dependencies && task.dependencies.length > 0) {
      lines.push(`**Depends on:** ${task.dependencies.join(', ')}`);
    }

    return lines.join('\n');
  }

  /**
   * Search for relevant references. Delegates to SharedContextState.
   */
  getRelevantReferences(query: string): Reference[] {
    return this.contextState.searchReferences(query);
  }

  // ---------------------------------------------------------------------------
  // Private helpers
  // ---------------------------------------------------------------------------

  private buildTaskSection(task: WorkerTask): string {
    const parts: string[] = ['## Task Assignment'];

    parts.push(`You are working on task **${task.id}**: ${task.description}`);

    if (task.context) {
      parts.push(`\n### Additional Context\n${task.context}`);
    }

    return parts.join('\n');
  }
}

// =============================================================================
// FACTORY
// =============================================================================

export function createSharedContextEngine(
  contextState: SharedContextState,
  config?: SharedContextEngineConfig,
): SharedContextEngine {
  return new SharedContextEngine(contextState, config);
}
