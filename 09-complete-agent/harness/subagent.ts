/**
 * Subagent System
 *
 * Spawns isolated agent instances for parallel task execution.
 * Each subagent has its own context and can run independently.
 */

import { Session } from './session.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Configuration for spawning a subagent.
 */
export interface SubagentConfig {
  /** Task description for the subagent */
  task: string;
  /** Optional system prompt override */
  systemPrompt?: string;
  /** Optional model override */
  model?: string;
  /** Maximum iterations for the subagent */
  maxIterations?: number;
  /** Tool names to enable (default: all) */
  enabledTools?: string[];
  /** Timeout in milliseconds */
  timeout?: number;
}

/**
 * Result from a subagent execution.
 */
export interface SubagentResult {
  /** Whether the task completed successfully */
  success: boolean;
  /** Final message/response */
  message: string;
  /** Subagent session ID */
  sessionId: string;
  /** Number of iterations used */
  iterations: number;
  /** Token usage */
  usage: {
    inputTokens: number;
    outputTokens: number;
    cachedTokens: number;
  };
  /** Execution time in milliseconds */
  executionTime: number;
  /** Error if failed */
  error?: Error;
}

/**
 * Task for parallel execution.
 */
export interface ParallelTask {
  id: string;
  config: SubagentConfig;
}

// =============================================================================
// SEMAPHORE FOR CONCURRENCY CONTROL
// =============================================================================

/**
 * Simple semaphore for limiting concurrent executions.
 */
class Semaphore {
  private permits: number;
  private waiting: Array<() => void> = [];

  constructor(permits: number) {
    this.permits = permits;
  }

  async acquire(): Promise<void> {
    if (this.permits > 0) {
      this.permits--;
      return;
    }

    return new Promise(resolve => {
      this.waiting.push(resolve);
    });
  }

  release(): void {
    const next = this.waiting.shift();
    if (next) {
      next();
    } else {
      this.permits++;
    }
  }
}

// =============================================================================
// SUBAGENT SPAWNER
// =============================================================================

/**
 * Manages subagent spawning and execution.
 *
 * Features:
 * - Isolated context per subagent
 * - Concurrent execution with limits
 * - Timeout handling
 * - Result aggregation
 *
 * @example
 * ```typescript
 * const spawner = new SubagentSpawner(parentSession, { maxConcurrent: 3 });
 *
 * // Spawn a single subagent
 * const result = await spawner.spawn({
 *   task: 'Read all TypeScript files and list their exports',
 * });
 *
 * // Run multiple tasks in parallel
 * const results = await spawner.runParallel([
 *   { id: 'search', config: { task: 'Search for API endpoints' } },
 *   { id: 'tests', config: { task: 'Find test files' } },
 * ]);
 * ```
 */
export class SubagentSpawner {
  private parentSession: Session;
  private semaphore: Semaphore;
  private activeSubagents: Map<string, Session> = new Map();
  private defaultTimeout: number;

  constructor(
    parentSession: Session,
    options: {
      maxConcurrent?: number;
      defaultTimeout?: number;
    } = {}
  ) {
    this.parentSession = parentSession;
    this.semaphore = new Semaphore(options.maxConcurrent ?? 5);
    this.defaultTimeout = options.defaultTimeout ?? 60000; // 1 minute
  }

  /**
   * Spawn a subagent and wait for completion.
   */
  async spawn(config: SubagentConfig): Promise<SubagentResult> {
    await this.semaphore.acquire();

    const startTime = Date.now();
    const timeout = config.timeout ?? this.defaultTimeout;

    // Create subagent session
    const subagent = this.parentSession.createSubagent({
      model: config.model,
      maxIterations: config.maxIterations,
    });

    this.activeSubagents.set(subagent.id, subagent);

    try {
      await subagent.initialize();

      // Add system prompt if provided
      if (config.systemPrompt) {
        subagent.contextManager.addSystemMessage(config.systemPrompt);
      }

      // Add the task
      subagent.addUserMessage(config.task);
      subagent.setState('running');

      // Run with timeout
      const result = await Promise.race([
        this.executeSubagent(subagent, config),
        this.timeoutPromise(timeout, subagent.id),
      ]);

      const executionTime = Date.now() - startTime;
      const stats = subagent.getStats();

      return {
        success: result.success,
        message: result.message,
        sessionId: subagent.id,
        iterations: result.iterations,
        usage: {
          inputTokens: stats.totalInputTokens,
          outputTokens: stats.totalOutputTokens,
          cachedTokens: stats.totalCachedTokens,
        },
        executionTime,
      };
    } catch (error) {
      const executionTime = Date.now() - startTime;
      return {
        success: false,
        message: `Subagent error: ${(error as Error).message}`,
        sessionId: subagent.id,
        iterations: 0,
        usage: { inputTokens: 0, outputTokens: 0, cachedTokens: 0 },
        executionTime,
        error: error as Error,
      };
    } finally {
      this.activeSubagents.delete(subagent.id);
      await subagent.cleanup();
      this.semaphore.release();
    }
  }

  /**
   * Run multiple tasks in parallel.
   */
  async runParallel(tasks: ParallelTask[]): Promise<Map<string, SubagentResult>> {
    const results = new Map<string, SubagentResult>();

    const promises = tasks.map(async task => {
      const result = await this.spawn(task.config);
      results.set(task.id, result);
    });

    await Promise.all(promises);
    return results;
  }

  /**
   * Cancel all active subagents.
   */
  async cancelAll(): Promise<void> {
    const cleanupPromises = Array.from(this.activeSubagents.values()).map(
      subagent => subagent.cleanup()
    );
    await Promise.all(cleanupPromises);
    this.activeSubagents.clear();
  }

  /**
   * Get count of active subagents.
   */
  getActiveCount(): number {
    return this.activeSubagents.size;
  }

  // ===========================================================================
  // PRIVATE METHODS
  // ===========================================================================

  /**
   * Execute a subagent's task.
   */
  private async executeSubagent(
    subagent: Session,
    config: SubagentConfig
  ): Promise<{ success: boolean; message: string; iterations: number }> {
    // This is a simplified execution - in practice, you'd use the full agent loop
    // For now, we'll do a simple request-response

    const messages = subagent.getMessages();

    let iterations = 0;
    const maxIterations = config.maxIterations ?? subagent.maxIterations;

    while (iterations < maxIterations) {
      iterations++;

      const response = await subagent.provider.chatWithTools(messages, {
        model: config.model ?? subagent.model,
        maxTokens: 4096,
      });

      // Update stats
      if (response.usage) {
        subagent.updateStats({
          inputTokens: response.usage.inputTokens,
          outputTokens: response.usage.outputTokens,
          cachedTokens: response.usage.cachedTokens,
        });
      }

      // Check for tool calls
      if (response.toolCalls && response.toolCalls.length > 0) {
        // Execute tools and continue loop
        for (const toolCall of response.toolCalls) {
          const args = JSON.parse(toolCall.function.arguments);
          const result = await subagent.toolRegistry.execute(
            toolCall.function.name,
            args
          );

          // Add to conversation
          messages.push({
            role: 'assistant',
            content: response.content || '',
            tool_calls: [toolCall],
          } as any);

          messages.push({
            role: 'tool',
            content: result.success
              ? `✓ Success\n\n${result.output}`
              : `✗ Failed\n\n${result.output}`,
            tool_call_id: toolCall.id,
            name: toolCall.function.name, // Required for Gemini
          } as any);

          subagent.updateStats({ inputTokens: 0, outputTokens: 0 }, 1);
        }
      } else {
        // No tool calls - task complete
        subagent.setState('completed');
        return {
          success: true,
          message: response.content,
          iterations,
        };
      }
    }

    // Max iterations reached
    subagent.setState('error');
    return {
      success: false,
      message: `Task incomplete: reached maximum iterations (${maxIterations})`,
      iterations,
    };
  }

  /**
   * Create a timeout promise.
   */
  private timeoutPromise(
    ms: number,
    sessionId: string
  ): Promise<never> {
    return new Promise((_, reject) => {
      setTimeout(() => {
        reject(new Error(`Subagent ${sessionId} timed out after ${ms}ms`));
      }, ms);
    });
  }
}

// =============================================================================
// FACTORY FUNCTION
// =============================================================================

/**
 * Create a subagent spawner for a session.
 */
export function createSubagentSpawner(
  session: Session,
  options?: {
    maxConcurrent?: number;
    defaultTimeout?: number;
  }
): SubagentSpawner {
  return new SubagentSpawner(session, options);
}
