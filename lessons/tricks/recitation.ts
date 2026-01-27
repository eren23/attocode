/**
 * Trick Q: Recitation / Goal Reinforcement
 *
 * Periodically injects task summaries (plans, todos, goals) into the END
 * of the context to combat "lost in the middle" attention issues.
 *
 * Problem: In long conversations (50+ tool calls), the model "forgets"
 * the original goal because it's buried in the middle of the context.
 *
 * Solution: Periodically "recite" the current goal/plan at the context end,
 * pushing it into the model's recent attention span.
 *
 * @example
 * ```typescript
 * import { createRecitationManager } from './recitation';
 *
 * const recitation = createRecitationManager({
 *   frequency: 5,  // Every 5 iterations
 *   sources: ['plan', 'todo', 'goal'],
 * });
 *
 * // In agent loop
 * const messages = recitation.injectIfNeeded(
 *   currentMessages,
 *   { plan, todos, goal, iteration: 15 }
 * );
 * ```
 */

// =============================================================================
// TYPES
// =============================================================================

/**
 * Sources of content to recite.
 */
export type RecitationSource = 'plan' | 'todo' | 'goal' | 'memory' | 'custom';

/**
 * Configuration for recitation.
 */
export interface RecitationConfig {
  /** Inject recitation every N iterations (default: 5) */
  frequency: number;

  /** Sources to include in recitation */
  sources: RecitationSource[];

  /** Maximum tokens for recitation block (default: 500) */
  maxTokens?: number;

  /** Custom recitation builder */
  customBuilder?: (state: RecitationState) => string | null;

  /** Whether to track injection history */
  trackHistory?: boolean;
}

/**
 * Current state for building recitation.
 */
export interface RecitationState {
  /** Current iteration number */
  iteration: number;

  /** Original user goal/task */
  goal?: string;

  /** Current plan with tasks */
  plan?: PlanState;

  /** Current todo list */
  todos?: TodoItem[];

  /** Relevant memory items */
  memories?: string[];

  /** Files currently being worked on */
  activeFiles?: string[];

  /** Recent errors encountered */
  recentErrors?: string[];

  /** Custom state values */
  custom?: Record<string, unknown>;
}

/**
 * Plan state.
 */
export interface PlanState {
  description: string;
  tasks: PlanTask[];
  currentTaskIndex: number;
}

/**
 * Task in a plan.
 */
export interface PlanTask {
  id: string;
  description: string;
  status: 'pending' | 'in_progress' | 'completed' | 'failed';
}

/**
 * Todo item.
 */
export interface TodoItem {
  content: string;
  status: 'pending' | 'in_progress' | 'completed';
}

/**
 * Message for injection.
 */
export interface RecitationMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
}

/**
 * Recitation history entry.
 */
export interface RecitationEntry {
  iteration: number;
  timestamp: string;
  content: string;
  sources: RecitationSource[];
}

/**
 * Events emitted by recitation manager.
 */
export type RecitationEvent =
  | { type: 'recitation.injected'; iteration: number; sources: RecitationSource[] }
  | { type: 'recitation.skipped'; iteration: number; reason: string }
  | { type: 'recitation.built'; content: string; tokenEstimate: number };

export type RecitationEventListener = (event: RecitationEvent) => void;

// =============================================================================
// RECITATION MANAGER
// =============================================================================

/**
 * Manages periodic goal/plan recitation.
 */
export class RecitationManager {
  private config: Required<RecitationConfig>;
  private history: RecitationEntry[] = [];
  private lastInjectionIteration = 0;
  private listeners: RecitationEventListener[] = [];

  constructor(config: RecitationConfig) {
    this.config = {
      frequency: config.frequency,
      sources: config.sources,
      maxTokens: config.maxTokens ?? 500,
      customBuilder: config.customBuilder ?? (() => null),
      trackHistory: config.trackHistory ?? true,
    };
  }

  /**
   * Check if recitation should be injected at this iteration.
   */
  shouldInject(iteration: number): boolean {
    // Always inject on first iteration
    if (iteration === 1) return true;

    // Inject every N iterations
    const iterationsSinceLastInjection = iteration - this.lastInjectionIteration;
    return iterationsSinceLastInjection >= this.config.frequency;
  }

  /**
   * Build recitation content from state.
   */
  buildRecitation(state: RecitationState): string | null {
    const parts: string[] = [];
    const usedSources: RecitationSource[] = [];

    // Goal
    if (this.config.sources.includes('goal') && state.goal) {
      parts.push(`**Goal**: ${state.goal}`);
      usedSources.push('goal');
    }

    // Plan progress
    if (this.config.sources.includes('plan') && state.plan) {
      const planSummary = this.buildPlanSummary(state.plan);
      if (planSummary) {
        parts.push(planSummary);
        usedSources.push('plan');
      }
    }

    // Todo list
    if (this.config.sources.includes('todo') && state.todos?.length) {
      const todoSummary = this.buildTodoSummary(state.todos);
      if (todoSummary) {
        parts.push(todoSummary);
        usedSources.push('todo');
      }
    }

    // Memory context
    if (this.config.sources.includes('memory') && state.memories?.length) {
      const memorySummary = this.buildMemorySummary(state.memories);
      if (memorySummary) {
        parts.push(memorySummary);
        usedSources.push('memory');
      }
    }

    // Custom content
    if (this.config.sources.includes('custom')) {
      const customContent = this.config.customBuilder(state);
      if (customContent) {
        parts.push(customContent);
        usedSources.push('custom');
      }
    }

    // Active files (always include if present)
    if (state.activeFiles?.length) {
      parts.push(`**Active files**: ${state.activeFiles.join(', ')}`);
    }

    // Recent errors (warn about them)
    if (state.recentErrors?.length) {
      parts.push(`**Recent errors**: ${state.recentErrors.slice(-2).join('; ')}`);
    }

    if (parts.length === 0) {
      return null;
    }

    const content = parts.join('\n\n');

    // Truncate if too long
    const tokenEstimate = Math.ceil(content.length / 4);
    if (tokenEstimate > this.config.maxTokens) {
      const truncated = this.truncateContent(content, this.config.maxTokens);
      this.emit({ type: 'recitation.built', content: truncated, tokenEstimate: this.config.maxTokens });
      return truncated;
    }

    this.emit({ type: 'recitation.built', content, tokenEstimate });
    return content;
  }

  /**
   * Inject recitation into messages if needed.
   * Returns the modified message array.
   */
  injectIfNeeded<T extends RecitationMessage>(
    messages: T[],
    state: RecitationState
  ): T[] {
    if (!this.shouldInject(state.iteration)) {
      this.emit({
        type: 'recitation.skipped',
        iteration: state.iteration,
        reason: 'not_due',
      });
      return messages;
    }

    const recitationContent = this.buildRecitation(state);
    if (!recitationContent) {
      this.emit({
        type: 'recitation.skipped',
        iteration: state.iteration,
        reason: 'no_content',
      });
      return messages;
    }

    // Create recitation message
    const recitationMessage = {
      role: 'system' as const,
      content: `[Current Status - Iteration ${state.iteration}]\n${recitationContent}`,
    } as T;

    // Track injection
    this.lastInjectionIteration = state.iteration;

    if (this.config.trackHistory) {
      this.history.push({
        iteration: state.iteration,
        timestamp: new Date().toISOString(),
        content: recitationContent,
        sources: this.config.sources.filter(s =>
          recitationContent.toLowerCase().includes(s.toLowerCase())
        ),
      });
    }

    this.emit({
      type: 'recitation.injected',
      iteration: state.iteration,
      sources: this.config.sources,
    });

    // Inject at the END of messages (before the final user message if present)
    const lastUserIndex = this.findLastUserMessageIndex(messages);
    if (lastUserIndex >= 0) {
      // Insert before the last user message
      return [
        ...messages.slice(0, lastUserIndex),
        recitationMessage,
        ...messages.slice(lastUserIndex),
      ];
    }

    // No user message at end, just append
    return [...messages, recitationMessage];
  }

  /**
   * Force recitation injection regardless of frequency.
   */
  forceInject<T extends RecitationMessage>(
    messages: T[],
    state: RecitationState
  ): T[] {
    const originalFrequency = this.config.frequency;
    this.config.frequency = 0; // Force injection
    const result = this.injectIfNeeded(messages, state);
    this.config.frequency = originalFrequency;
    return result;
  }

  /**
   * Get injection history.
   */
  getHistory(): RecitationEntry[] {
    return [...this.history];
  }

  /**
   * Clear history.
   */
  clearHistory(): void {
    this.history = [];
    this.lastInjectionIteration = 0;
  }

  /**
   * Update configuration.
   */
  updateConfig(updates: Partial<RecitationConfig>): void {
    Object.assign(this.config, updates);
  }

  /**
   * Subscribe to events.
   */
  on(listener: RecitationEventListener): () => void {
    this.listeners.push(listener);
    return () => {
      const idx = this.listeners.indexOf(listener);
      if (idx >= 0) this.listeners.splice(idx, 1);
    };
  }

  // Internal methods

  private buildPlanSummary(plan: PlanState): string {
    const completedCount = plan.tasks.filter(t => t.status === 'completed').length;
    const totalCount = plan.tasks.length;
    const currentTask = plan.tasks[plan.currentTaskIndex];

    const lines = [
      `**Plan Progress**: ${completedCount}/${totalCount} tasks completed`,
    ];

    if (currentTask) {
      lines.push(`**Current Task**: ${currentTask.description}`);
    }

    // Show next pending tasks (max 2)
    const pendingTasks = plan.tasks
      .filter(t => t.status === 'pending')
      .slice(0, 2);

    if (pendingTasks.length > 0) {
      lines.push('**Next**: ' + pendingTasks.map(t => t.description).join('; '));
    }

    return lines.join('\n');
  }

  private buildTodoSummary(todos: TodoItem[]): string {
    const pending = todos.filter(t => t.status === 'pending');
    const inProgress = todos.filter(t => t.status === 'in_progress');
    const completed = todos.filter(t => t.status === 'completed');

    const lines = [
      `**Todo Status**: ${completed.length} done, ${inProgress.length} active, ${pending.length} pending`,
    ];

    if (inProgress.length > 0) {
      lines.push('**In Progress**: ' + inProgress.map(t => t.content).join('; '));
    }

    if (pending.length > 0 && pending.length <= 3) {
      lines.push('**Remaining**: ' + pending.map(t => t.content).join('; '));
    } else if (pending.length > 3) {
      lines.push(
        '**Next**: ' + pending.slice(0, 3).map(t => t.content).join('; ') +
        ` (+${pending.length - 3} more)`
      );
    }

    return lines.join('\n');
  }

  private buildMemorySummary(memories: string[]): string {
    if (memories.length === 0) return '';

    const maxMemories = 3;
    const shown = memories.slice(0, maxMemories);

    let summary = '**Relevant Context**: ' + shown.join('; ');
    if (memories.length > maxMemories) {
      summary += ` (+${memories.length - maxMemories} more)`;
    }

    return summary;
  }

  private truncateContent(content: string, maxTokens: number): string {
    const maxChars = maxTokens * 4;
    if (content.length <= maxChars) return content;

    return content.slice(0, maxChars - 20) + '\n...[truncated]';
  }

  private findLastUserMessageIndex<T extends RecitationMessage>(messages: T[]): number {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === 'user') {
        return i;
      }
    }
    return -1;
  }

  private emit(event: RecitationEvent): void {
    for (const listener of this.listeners) {
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
 * Create a recitation manager.
 *
 * @example
 * ```typescript
 * const recitation = createRecitationManager({
 *   frequency: 5,  // Every 5 iterations
 *   sources: ['goal', 'plan', 'todo'],
 *   maxTokens: 500,
 * });
 *
 * // In agent loop
 * const enrichedMessages = recitation.injectIfNeeded(messages, {
 *   iteration: currentIteration,
 *   goal: 'Implement user authentication',
 *   plan: currentPlan,
 *   todos: currentTodos,
 * });
 * ```
 */
export function createRecitationManager(
  config: RecitationConfig
): RecitationManager {
  return new RecitationManager(config);
}

// =============================================================================
// UTILITIES
// =============================================================================

/**
 * Quick helper to build a recitation block without full manager.
 */
export function buildQuickRecitation(state: RecitationState): string {
  const parts: string[] = [];

  if (state.goal) {
    parts.push(`Goal: ${state.goal}`);
  }

  if (state.plan) {
    const completed = state.plan.tasks.filter(t => t.status === 'completed').length;
    parts.push(`Progress: ${completed}/${state.plan.tasks.length} tasks`);

    const current = state.plan.tasks[state.plan.currentTaskIndex];
    if (current) {
      parts.push(`Current: ${current.description}`);
    }
  }

  if (state.todos?.length) {
    const pending = state.todos.filter(t => t.status !== 'completed').length;
    parts.push(`Todos: ${pending} remaining`);
  }

  return parts.join(' | ');
}

/**
 * Calculate optimal recitation frequency based on context size.
 * Longer contexts need more frequent recitation.
 */
export function calculateOptimalFrequency(contextTokens: number): number {
  if (contextTokens < 10000) return 10;  // Light context
  if (contextTokens < 30000) return 7;   // Medium context
  if (contextTokens < 60000) return 5;   // Heavy context
  return 3;  // Very heavy context - recite often
}

/**
 * Format recitation history for debugging.
 */
export function formatRecitationHistory(history: RecitationEntry[]): string {
  if (history.length === 0) {
    return 'No recitation history.';
  }

  const lines = ['Recitation History:', ''];

  for (const entry of history.slice(-5)) {
    lines.push(`[Iteration ${entry.iteration}] (${entry.sources.join(', ')})`);
    lines.push(`  ${entry.content.slice(0, 100)}${entry.content.length > 100 ? '...' : ''}`);
    lines.push('');
  }

  return lines.join('\n');
}
