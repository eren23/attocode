/**
 * Subagent System
 *
 * Spawns isolated agent instances for parallel task execution.
 * Each subagent has its own context and can run independently.
 *
 * Enhanced with SharedBlackboard support for real-time coordination:
 * - Subagents can post findings for other agents to see
 * - Subagents can subscribe to relevant findings
 * - Resource claiming prevents file edit conflicts
 */

import { Session } from './session.js';

// =============================================================================
// BLACKBOARD TYPES (inline to avoid circular dependencies)
// =============================================================================

/**
 * A finding posted to the blackboard by an agent.
 */
export interface Finding {
  id: string;
  agentId: string;
  topic: string;
  content: string;
  confidence: number;
  type: FindingType;
  relatedFiles?: string[];
  relatedSymbols?: string[];
  tags?: string[];
  timestamp: Date;
  supersedesId?: string;
  metadata?: Record<string, unknown>;
}

export type FindingType =
  | 'discovery'
  | 'analysis'
  | 'solution'
  | 'problem'
  | 'question'
  | 'answer'
  | 'progress'
  | 'blocker'
  | 'resource';

/**
 * Interface for shared blackboard (minimal subset needed by subagents).
 */
export interface SharedBlackboardInterface {
  post(agentId: string, input: Omit<Finding, 'id' | 'agentId' | 'timestamp'>): Finding;
  query(filter?: { topic?: string; agentId?: string; types?: FindingType[] }): Finding[];
  subscribe(options: {
    agentId: string;
    topicPattern?: string;
    types?: FindingType[];
    callback: (finding: Finding) => void;
  }): string;
  unsubscribe(subscriptionId: string): boolean;
  claim(resource: string, agentId: string, type: 'read' | 'write' | 'exclusive'): boolean;
  release(resource: string, agentId: string): boolean;
  isClaimed(resource: string): boolean;
}

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
  /** Shared blackboard for coordination with other subagents */
  blackboard?: SharedBlackboardInterface;
  /** Topic to subscribe to on the blackboard */
  subscribeTopics?: string[];
  /** Whether to auto-post progress updates to blackboard */
  autoPostProgress?: boolean;
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
  /** Findings posted to the blackboard */
  findings?: Finding[];
  /** Files modified by this subagent */
  filesModified?: string[];
}

/**
 * Task for parallel execution.
 */
export interface ParallelTask {
  id: string;
  config: SubagentConfig;
}

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

/**
 * Check if a tool is a file write operation.
 */
function isFileWriteTool(toolName: string): boolean {
  const writeTools = [
    'write_file', 'writeFile', 'write',
    'edit_file', 'editFile', 'edit',
    'create_file', 'createFile', 'create',
    'patch_file', 'patchFile', 'patch',
    'delete_file', 'deleteFile', 'delete',
    'move_file', 'moveFile', 'move',
    'rename_file', 'renameFile', 'rename',
  ];
  return writeTools.some((t) => toolName.toLowerCase().includes(t.toLowerCase()));
}

/**
 * Check if a tool produces discovery/research findings.
 */
function isDiscoveryTool(toolName: string): boolean {
  const discoveryTools = [
    'read_file', 'readFile', 'read',
    'search', 'grep', 'find',
    'list_files', 'listFiles', 'ls',
    'get_', 'fetch_',
    'analyze', 'inspect',
  ];
  return discoveryTools.some((t) => toolName.toLowerCase().includes(t.toLowerCase()));
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

    // Track findings posted by this subagent
    const postedFindings: Finding[] = [];
    let subscriptionId: string | undefined;

    // Set up blackboard integration
    if (config.blackboard) {
      // Subscribe to relevant topics
      if (config.subscribeTopics && config.subscribeTopics.length > 0) {
        for (const topic of config.subscribeTopics) {
          subscriptionId = config.blackboard.subscribe({
            agentId: subagent.id,
            topicPattern: topic,
            callback: (finding) => {
              // Inject finding into subagent context
              subagent.contextManager.addSystemMessage(
                `[Blackboard Update] ${finding.agentId} found: ${finding.content}`
              );
            },
          });
        }
      }

      // Post initial progress
      if (config.autoPostProgress) {
        const progressFinding = config.blackboard.post(subagent.id, {
          topic: 'progress',
          content: `Started task: ${config.task}`,
          type: 'progress',
          confidence: 1,
        });
        postedFindings.push(progressFinding);
      }
    }

    try {
      await subagent.initialize();

      // Add system prompt if provided
      if (config.systemPrompt) {
        subagent.contextManager.addSystemMessage(config.systemPrompt);
      }

      // Add blackboard context to system prompt
      if (config.blackboard) {
        const existingFindings = config.blackboard.query({ types: ['discovery', 'analysis'] });
        if (existingFindings.length > 0) {
          const contextSummary = existingFindings
            .slice(0, 5)
            .map((f) => `- [${f.agentId}] ${f.content}`)
            .join('\n');
          subagent.contextManager.addSystemMessage(
            `[Blackboard Context] Relevant findings from other agents:\n${contextSummary}`
          );
        }
      }

      // Add the task
      subagent.addUserMessage(config.task);
      subagent.setState('running');

      // Run with timeout
      const result = await Promise.race([
        this.executeSubagent(subagent, config, postedFindings),
        this.timeoutPromise(timeout, subagent.id),
      ]);

      // Post completion to blackboard
      if (config.blackboard && config.autoPostProgress) {
        const completionFinding = config.blackboard.post(subagent.id, {
          topic: 'progress',
          content: `Completed task: ${result.success ? 'SUCCESS' : 'FAILED'} - ${result.message.slice(0, 200)}`,
          type: result.success ? 'progress' : 'blocker',
          confidence: 1,
        });
        postedFindings.push(completionFinding);
      }

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
        findings: postedFindings.length > 0 ? postedFindings : undefined,
        filesModified: result.filesModified,
      };
    } catch (error) {
      // Post error to blackboard
      if (config.blackboard && config.autoPostProgress) {
        config.blackboard.post(subagent.id, {
          topic: 'progress',
          content: `Error: ${(error as Error).message}`,
          type: 'blocker',
          confidence: 1,
        });
      }

      const executionTime = Date.now() - startTime;
      return {
        success: false,
        message: `Subagent error: ${(error as Error).message}`,
        sessionId: subagent.id,
        iterations: 0,
        usage: { inputTokens: 0, outputTokens: 0, cachedTokens: 0 },
        executionTime,
        error: error as Error,
        findings: postedFindings.length > 0 ? postedFindings : undefined,
      };
    } finally {
      // Cleanup blackboard subscriptions
      if (config.blackboard && subscriptionId) {
        config.blackboard.unsubscribe(subscriptionId);
      }

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
    config: SubagentConfig,
    postedFindings: Finding[] = []
  ): Promise<{ success: boolean; message: string; iterations: number; filesModified?: string[] }> {
    // This is a simplified execution - in practice, you'd use the full agent loop
    // For now, we'll do a simple request-response

    const messages = subagent.getMessages();
    const filesModified: string[] = [];

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
          const toolName = toolCall.function.name;

          // Claim resource if this is a file write operation
          if (config.blackboard && isFileWriteTool(toolName)) {
            const filePath = args.path || args.file_path || args.filePath;
            if (filePath) {
              const claimed = config.blackboard.claim(filePath, subagent.id, 'write');
              if (!claimed) {
                // Another agent is modifying this file - skip or wait
                messages.push({
                  role: 'tool',
                  content: `✗ Resource conflict: ${filePath} is being modified by another agent`,
                  tool_call_id: toolCall.id,
                  name: toolName,
                } as any);
                continue;
              }
            }
          }

          const result = await subagent.toolRegistry.execute(toolName, args);

          // Track file modifications
          if (result.success && isFileWriteTool(toolName)) {
            const filePath = args.path || args.file_path || args.filePath;
            if (filePath && !filesModified.includes(filePath)) {
              filesModified.push(filePath);

              // Release the claim
              if (config.blackboard) {
                config.blackboard.release(filePath, subagent.id);
              }
            }
          }

          // Post significant findings to blackboard
          if (config.blackboard && result.success && isDiscoveryTool(toolName)) {
            const finding = config.blackboard.post(subagent.id, {
              topic: 'discovery',
              content: `Found via ${toolName}: ${String(result.output).slice(0, 500)}`,
              type: 'discovery',
              confidence: 0.8,
              relatedFiles: args.path ? [args.path] : undefined,
            });
            postedFindings.push(finding);
          }

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
            name: toolName,
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
          filesModified: filesModified.length > 0 ? filesModified : undefined,
        };
      }
    }

    // Max iterations reached
    subagent.setState('error');
    return {
      success: false,
      message: `Task incomplete: reached maximum iterations (${maxIterations})`,
      iterations,
      filesModified: filesModified.length > 0 ? filesModified : undefined,
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
