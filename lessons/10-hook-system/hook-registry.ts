/**
 * Lesson 10: Hook Registry
 *
 * The hook registry manages hook registration and execution.
 * Unlike the event bus which is for observation only, hooks
 * can intercept and modify events.
 *
 * Key concepts:
 * - Hooks are executed in priority order (lower = earlier)
 * - Hooks can modify events (intercepting) or just observe
 * - Error handling strategies: continue, stop, or collect
 * - Performance tracking for debugging slow hooks
 */

import type {
  Hook,
  AgentEvent,
  AgentEventType,
  EventOfType,
  HookHandler,
  HookRegistrationOptions,
  HookExecutionResult,
  HookError,
  HookStats,
} from './types.js';

// =============================================================================
// HOOK REGISTRY
// =============================================================================

/**
 * Error handling strategy when a hook fails.
 */
export type ErrorStrategy = 'continue' | 'stop' | 'collect';

/**
 * Configuration for the hook registry.
 */
export interface HookRegistryConfig {
  /** How to handle errors in hooks */
  errorStrategy: ErrorStrategy;
  /** Enable performance tracking */
  trackPerformance: boolean;
  /** Log hook execution */
  debug: boolean;
}

const DEFAULT_CONFIG: HookRegistryConfig = {
  errorStrategy: 'continue',
  trackPerformance: false,
  debug: false,
};

/**
 * Registry for managing and executing hooks.
 *
 * Example usage:
 * ```ts
 * const registry = new HookRegistry();
 *
 * // Register a hook
 * registry.register({
 *   id: 'log-tool-calls',
 *   event: 'tool.before',
 *   handler: (event) => console.log('Tool:', event.tool),
 *   priority: 100,
 * });
 *
 * // Execute hooks for an event
 * const result = await registry.execute(event);
 * if (result.prevented) {
 *   console.log('Event was prevented by a hook');
 * }
 * ```
 */
export class HookRegistry {
  // Hooks organized by event type, sorted by priority
  private hooks: Map<AgentEventType, Hook[]> = new Map();

  // Performance stats per hook
  private stats: Map<string, HookStats> = new Map();

  // Configuration
  private config: HookRegistryConfig;

  constructor(config: Partial<HookRegistryConfig> = {}) {
    this.config = { ...DEFAULT_CONFIG, ...config };
  }

  // =============================================================================
  // REGISTRATION METHODS
  // =============================================================================

  /**
   * Register a hook.
   *
   * @param hook - The hook definition
   * @returns Unregister function
   */
  register<T extends AgentEventType>(hook: Hook<T>): () => void {
    const eventHooks = this.hooks.get(hook.event) ?? [];

    // Add hook with default priority
    const hookWithDefaults: Hook = {
      ...hook,
      priority: hook.priority ?? 100,
      canModify: hook.canModify ?? false,
    };

    eventHooks.push(hookWithDefaults);

    // Sort by priority (lower first)
    eventHooks.sort((a, b) => (a.priority ?? 100) - (b.priority ?? 100));

    this.hooks.set(hook.event, eventHooks);

    if (this.config.debug) {
      console.log(`[HookRegistry] Registered hook "${hook.id}" for "${hook.event}"`);
    }

    // Initialize stats
    if (this.config.trackPerformance) {
      this.stats.set(hook.id, {
        hookId: hook.id,
        event: hook.event,
        invocations: 0,
        errors: 0,
        totalDurationMs: 0,
        averageDurationMs: 0,
      });
    }

    // Return unregister function
    return () => this.unregister(hook.id);
  }

  /**
   * Convenient method to register a hook with just a handler.
   *
   * @param event - Event type to listen for
   * @param handler - Handler function
   * @param options - Optional registration options
   * @returns Unregister function
   */
  on<T extends AgentEventType>(
    event: T,
    handler: HookHandler<T>,
    options: HookRegistrationOptions = {}
  ): () => void {
    const hook: Hook<T> = {
      id: `hook-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      event,
      handler,
      ...options,
    };
    return this.register(hook);
  }

  /**
   * Unregister a hook by ID.
   *
   * @param hookId - The hook ID to remove
   * @returns Whether the hook was found and removed
   */
  unregister(hookId: string): boolean {
    for (const [event, hooks] of this.hooks.entries()) {
      const index = hooks.findIndex((h) => h.id === hookId);
      if (index !== -1) {
        hooks.splice(index, 1);
        if (this.config.debug) {
          console.log(`[HookRegistry] Unregistered hook "${hookId}"`);
        }
        return true;
      }
    }
    return false;
  }

  /**
   * Get all hooks for an event type.
   */
  getHooks(event: AgentEventType): Hook[] {
    return this.hooks.get(event) ?? [];
  }

  /**
   * Check if any hooks are registered for an event.
   */
  hasHooks(event: AgentEventType): boolean {
    const hooks = this.hooks.get(event);
    return hooks !== undefined && hooks.length > 0;
  }

  // =============================================================================
  // EXECUTION METHODS
  // =============================================================================

  /**
   * Execute all hooks for an event.
   *
   * This is where the magic happens! Hooks are executed in priority order,
   * and can modify the event or prevent further processing.
   *
   * USER CONTRIBUTION OPPORTUNITY:
   * The executeHooks method below handles hook ordering and error handling.
   * Consider these trade-offs:
   * - Should we stop on first error or continue?
   * - Should modifying hooks run before observing hooks?
   * - How do we handle async hooks that timeout?
   *
   * @param event - The event to process
   * @returns Execution result with timing and error info
   */
  async execute<T extends AgentEvent>(event: T): Promise<HookExecutionResult> {
    const hooks = this.hooks.get(event.type) ?? [];
    const startTime = performance.now();
    const errors: HookError[] = [];
    let prevented = false;
    let hooksExecuted = 0;

    // Execute hooks in priority order
    for (const hook of hooks) {
      // Check if event was prevented
      if (prevented && event.type === 'tool.before') {
        break;
      }

      const hookStartTime = performance.now();

      try {
        if (this.config.debug) {
          console.log(`[HookRegistry] Executing hook "${hook.id}" for "${event.type}"`);
        }

        // Execute the hook
        const result = hook.handler(event as EventOfType<typeof hook.event>);

        // Handle async hooks
        if (result instanceof Promise) {
          await result;
        }

        hooksExecuted++;

        // Check if hook prevented the event (only for tool.before)
        if (event.type === 'tool.before' && (event as any).preventDefault) {
          prevented = true;
          if (this.config.debug) {
            console.log(`[HookRegistry] Event prevented by hook "${hook.id}"`);
          }
        }

        // Update stats
        if (this.config.trackPerformance) {
          this.updateStats(hook.id, hookStartTime, false);
        }
      } catch (err) {
        const error = err instanceof Error ? err : new Error(String(err));

        errors.push({
          hookId: hook.id,
          error,
          event: event.type,
        });

        // Update stats
        if (this.config.trackPerformance) {
          this.updateStats(hook.id, hookStartTime, true);
        }

        // Handle based on error strategy
        switch (this.config.errorStrategy) {
          case 'stop':
            if (this.config.debug) {
              console.error(`[HookRegistry] Hook "${hook.id}" failed, stopping:`, error);
            }
            return {
              success: false,
              hooksExecuted,
              errors,
              durationMs: performance.now() - startTime,
              prevented,
            };

          case 'collect':
          case 'continue':
          default:
            if (this.config.debug) {
              console.error(`[HookRegistry] Hook "${hook.id}" failed, continuing:`, error);
            }
            break;
        }
      }
    }

    return {
      success: errors.length === 0,
      hooksExecuted,
      errors,
      durationMs: performance.now() - startTime,
      prevented,
    };
  }

  /**
   * Execute hooks synchronously (faster, but no async support).
   */
  executeSync<T extends AgentEvent>(event: T): HookExecutionResult {
    const hooks = this.hooks.get(event.type) ?? [];
    const startTime = performance.now();
    const errors: HookError[] = [];
    let prevented = false;
    let hooksExecuted = 0;

    for (const hook of hooks) {
      if (prevented && event.type === 'tool.before') {
        break;
      }

      try {
        const result = hook.handler(event as any);

        // Warn if handler returns a promise
        if (result instanceof Promise) {
          console.warn(
            `[HookRegistry] Async hook "${hook.id}" in sync execution, result ignored`
          );
        }

        hooksExecuted++;

        if (event.type === 'tool.before' && (event as any).preventDefault) {
          prevented = true;
        }
      } catch (err) {
        const error = err instanceof Error ? err : new Error(String(err));
        errors.push({ hookId: hook.id, error, event: event.type });

        if (this.config.errorStrategy === 'stop') {
          break;
        }
      }
    }

    return {
      success: errors.length === 0,
      hooksExecuted,
      errors,
      durationMs: performance.now() - startTime,
      prevented,
    };
  }

  // =============================================================================
  // STATISTICS
  // =============================================================================

  /**
   * Get performance statistics for a hook.
   */
  getStats(hookId: string): HookStats | undefined {
    return this.stats.get(hookId);
  }

  /**
   * Get all hook statistics.
   */
  getAllStats(): HookStats[] {
    return [...this.stats.values()];
  }

  /**
   * Reset all statistics.
   */
  resetStats(): void {
    for (const stats of this.stats.values()) {
      stats.invocations = 0;
      stats.errors = 0;
      stats.totalDurationMs = 0;
      stats.averageDurationMs = 0;
    }
  }

  /**
   * Update statistics for a hook execution.
   */
  private updateStats(hookId: string, startTime: number, hadError: boolean): void {
    const stats = this.stats.get(hookId);
    if (!stats) return;

    const duration = performance.now() - startTime;
    stats.invocations++;
    stats.totalDurationMs += duration;
    stats.averageDurationMs = stats.totalDurationMs / stats.invocations;

    if (hadError) {
      stats.errors++;
    }
  }

  // =============================================================================
  // UTILITY METHODS
  // =============================================================================

  /**
   * Clear all hooks.
   */
  clear(): void {
    this.hooks.clear();
    this.stats.clear();
  }

  /**
   * Get a summary of all registered hooks.
   */
  summary(): string {
    const lines: string[] = ['Hook Registry Summary:', ''];

    for (const [event, hooks] of this.hooks.entries()) {
      lines.push(`  ${event}:`);
      for (const hook of hooks) {
        const modifyFlag = hook.canModify ? ' [modify]' : '';
        lines.push(`    - ${hook.id} (priority: ${hook.priority})${modifyFlag}`);
        if (hook.description) {
          lines.push(`      ${hook.description}`);
        }
      }
    }

    return lines.join('\n');
  }
}

// =============================================================================
// GLOBAL REGISTRY
// =============================================================================

/**
 * Global hook registry instance.
 */
export const globalHookRegistry = new HookRegistry({
  errorStrategy: 'continue',
  trackPerformance: true,
  debug: false,
});
