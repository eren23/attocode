/**
 * JSONL Trace Parser
 *
 * Parses trace JSONL files into structured ParsedSession objects.
 * Handles event correlation, iteration grouping, and metric aggregation.
 */

import { createReadStream } from 'node:fs';
import { createInterface } from 'node:readline';
import type {
  ParsedEvent,
  ParsedIteration,
  ParsedSession,
  ParsedTask,
  SessionMetrics,
} from '../types.js';

// =============================================================================
// JSONL EVENT TYPES (mirrors src/tracing/types.ts)
// =============================================================================

interface BaseJSONLEntry {
  _type: string;
  _ts: string;
  traceId: string;
}

interface SessionStartEntry extends BaseJSONLEntry {
  _type: 'session.start';
  sessionId: string;
  task?: string;
  model: string;
  metadata: Record<string, unknown>;
}

interface SessionEndEntry extends BaseJSONLEntry {
  _type: 'session.end';
  sessionId: string;
  status: string;
  durationMs: number;
  metrics: Record<string, number>;
}

interface TaskStartEntry extends BaseJSONLEntry {
  _type: 'task.start';
  taskId: string;
  sessionId: string;
  prompt: string;
  taskNumber: number;
}

interface TaskEndEntry extends BaseJSONLEntry {
  _type: 'task.end';
  taskId: string;
  sessionId: string;
  status: string;
  durationMs: number;
  metrics?: {
    inputTokens: number;
    outputTokens: number;
    cacheHitRate: number;
    toolCalls: number;
    totalCost: number;
  };
  result?: {
    success: boolean;
    output?: string;
    failureReason?: string;
  };
}

interface LLMRequestEntry extends BaseJSONLEntry {
  _type: 'llm.request';
  requestId: string;
  model: string;
  messageCount: number;
  toolCount: number;
  estimatedInputTokens: number;
}

interface LLMResponseEntry extends BaseJSONLEntry {
  _type: 'llm.response';
  requestId: string;
  durationMs: number;
  tokens: {
    input: number;
    output: number;
  };
  cache: {
    cacheReadTokens: number;
    hitRate: number;
  };
  stopReason: string;
  toolCallCount: number;
}

interface ToolExecutionEntry extends BaseJSONLEntry {
  _type: 'tool.execution';
  executionId: string;
  toolName: string;
  durationMs: number;
  status: string;
  resultSize?: number;
  /** Tool input arguments (truncated for large values) */
  input?: Record<string, unknown>;
  /** Preview of the result (truncated) */
  outputPreview?: string;
  /** Error message if status is error */
  errorMessage?: string;
}

interface ThinkingEntry extends BaseJSONLEntry {
  _type: 'llm.thinking';
  requestId: string;
  thinking: {
    id: string;
    content: string;
    estimatedTokens: number;
    summarized: boolean;
    originalLength?: number;
  };
}

interface DecisionEntry extends BaseJSONLEntry {
  _type: 'decision';
  decision: {
    decisionId: string;
    type: string;
    decision: string;
    outcome: string;
    reasoning: string;
  };
}

interface SubagentLinkEntry extends BaseJSONLEntry {
  _type: 'subagent.link';
  link: {
    childSessionId: string;
    childConfig: {
      agentType: string;
      task: string;
    };
    result?: {
      success: boolean;
      tokensUsed: number;
      durationMs: number;
    };
  };
}

interface IterationWrapperEntry extends BaseJSONLEntry {
  _type: 'iteration.wrapper';
  iterationNumber: number;
  phase: 'start' | 'end';
  metrics?: {
    inputTokens: number;
    outputTokens: number;
    cacheHitRate: number;
    toolCallCount: number;
    totalCost: number;
  };
}

interface ErrorEntry extends BaseJSONLEntry {
  _type: 'error';
  errorCode: string;
  errorMessage: string;
  context: string;
  recoverable: boolean;
}

type TraceEntry =
  | SessionStartEntry
  | SessionEndEntry
  | TaskStartEntry
  | TaskEndEntry
  | LLMRequestEntry
  | LLMResponseEntry
  | ToolExecutionEntry
  | ThinkingEntry
  | DecisionEntry
  | SubagentLinkEntry
  | IterationWrapperEntry
  | ErrorEntry;

// =============================================================================
// PARSER CLASS
// =============================================================================

/**
 * Parses JSONL trace files into structured session data.
 */
export class JSONLParser {
  private events: ParsedEvent[] = [];
  private rawEntries: TraceEntry[] = [];

  /**
   * Parse a JSONL file and return a structured session.
   */
  async parseFile(filePath: string): Promise<ParsedSession> {
    this.events = [];
    this.rawEntries = [];

    // Read file line by line
    const fileStream = createReadStream(filePath);
    const rl = createInterface({
      input: fileStream,
      crlfDelay: Infinity,
    });

    for await (const line of rl) {
      if (!line.trim()) continue;

      try {
        const entry = JSON.parse(line) as TraceEntry;
        this.rawEntries.push(entry);
        this.events.push({
          type: entry._type,
          timestamp: new Date(entry._ts),
          traceId: entry.traceId,
          data: entry as unknown as Record<string, unknown>,
        });
      } catch (err) {
        console.warn(`Failed to parse line: ${line.slice(0, 100)}...`);
      }
    }

    return this.buildSession();
  }

  /**
   * Parse JSONL content string.
   */
  parseString(content: string): ParsedSession {
    this.events = [];
    this.rawEntries = [];

    const lines = content.split('\n');
    for (const line of lines) {
      if (!line.trim()) continue;

      try {
        const entry = JSON.parse(line) as TraceEntry;
        this.rawEntries.push(entry);
        this.events.push({
          type: entry._type,
          timestamp: new Date(entry._ts),
          traceId: entry.traceId,
          data: entry as unknown as Record<string, unknown>,
        });
      } catch {
        // Skip malformed lines
      }
    }

    return this.buildSession();
  }

  /**
   * Build structured session from parsed events.
   */
  private buildSession(): ParsedSession {
    // Find session start/end
    const sessionStart = this.rawEntries.find(
      e => e._type === 'session.start'
    ) as SessionStartEntry | undefined;
    const sessionEnd = this.rawEntries.find(
      e => e._type === 'session.end'
    ) as SessionEndEntry | undefined;

    // Build tasks (for terminal sessions with multiple prompts)
    const tasks = this.buildTasks();

    // Group events by iteration (aggregated from all tasks, or direct if no tasks)
    const iterations = tasks.length > 0
      ? tasks.flatMap(t => t.iterations)
      : this.buildIterations();

    // Extract subagent links
    const subagentLinks = this.rawEntries
      .filter((e): e is SubagentLinkEntry => e._type === 'subagent.link')
      .map(e => ({
        childSessionId: e.link.childSessionId,
        agentType: e.link.childConfig.agentType,
        task: e.link.childConfig.task,
        success: e.link.result?.success,
        tokensUsed: e.link.result?.tokensUsed,
        durationMs: e.link.result?.durationMs,
      }));

    // Extract errors
    const errors = this.rawEntries
      .filter((e): e is ErrorEntry => e._type === 'error')
      .map(e => ({
        code: e.errorCode,
        message: e.errorMessage,
        context: e.context,
        recoverable: e.recoverable,
        timestamp: new Date(e._ts),
      }));

    // Calculate metrics from all iterations
    const metrics = this.calculateMetrics(iterations);

    const startTime = sessionStart
      ? new Date(sessionStart._ts)
      : this.events[0]?.timestamp || new Date();

    const endTime = sessionEnd
      ? new Date(sessionEnd._ts)
      : this.events[this.events.length - 1]?.timestamp;

    return {
      sessionId: sessionStart?.sessionId || 'unknown',
      traceId: sessionStart?.traceId || 'unknown',
      task: sessionStart?.task || '', // Empty for terminal sessions
      model: sessionStart?.model || 'unknown',
      startTime,
      endTime,
      durationMs: sessionEnd?.durationMs || (endTime ? endTime.getTime() - startTime.getTime() : undefined),
      status: (sessionEnd?.status as ParsedSession['status']) || 'running',
      tasks,
      iterations,
      subagentLinks,
      memoryRetrievals: [], // TODO: Parse memory.retrieval events
      planEvolutions: [], // TODO: Parse plan.evolution events
      errors,
      metrics,
    };
  }

  /**
   * Build task objects from task.start/task.end entries.
   * Returns empty array if no tasks found (backward compatibility with single-task sessions).
   */
  private buildTasks(): ParsedTask[] {
    const tasks: ParsedTask[] = [];

    // Find all task-related entries
    const taskStartEntries = this.rawEntries
      .filter((e): e is TaskStartEntry => e._type === 'task.start');

    const taskEndEntries = this.rawEntries
      .filter((e): e is TaskEndEntry => e._type === 'task.end');

    // No tasks - this is a single-task session
    if (taskStartEntries.length === 0) {
      return [];
    }

    // Build iterations for all tasks
    const allIterations = this.buildIterations();

    // Match task boundaries with iterations by timestamp
    for (const taskStart of taskStartEntries) {
      const taskEnd = taskEndEntries.find(te => te.taskId === taskStart.taskId);

      // Find iterations that belong to this task (between task.start and task.end)
      const taskStartTime = new Date(taskStart._ts).getTime();
      const taskEndTime = taskEnd ? new Date(taskEnd._ts).getTime() : Date.now();

      const taskIterations = allIterations.filter(iter => {
        const iterTime = iter.startTime.getTime();
        return iterTime >= taskStartTime && iterTime <= taskEndTime;
      });

      const task: ParsedTask = {
        taskId: taskStart.taskId,
        taskNumber: taskStart.taskNumber,
        prompt: taskStart.prompt,
        startTime: new Date(taskStart._ts),
        endTime: taskEnd ? new Date(taskEnd._ts) : undefined,
        durationMs: taskEnd?.durationMs,
        status: (taskEnd?.status as ParsedTask['status']) || 'running',
        iterations: taskIterations,
        metrics: taskEnd?.metrics || {
          inputTokens: taskIterations.reduce((sum, i) => sum + i.metrics.inputTokens, 0),
          outputTokens: taskIterations.reduce((sum, i) => sum + i.metrics.outputTokens, 0),
          cacheHitRate: taskIterations.length > 0
            ? taskIterations.reduce((sum, i) => sum + i.metrics.cacheHitRate, 0) / taskIterations.length
            : 0,
          toolCalls: taskIterations.reduce((sum, i) => sum + i.tools.length, 0),
          totalCost: taskIterations.reduce((sum, i) => sum + i.metrics.cost, 0),
        },
        result: taskEnd?.result,
      };

      tasks.push(task);
    }

    return tasks;
  }

  /**
   * Build iteration objects from events.
   */
  private buildIterations(): ParsedIteration[] {
    const iterations: ParsedIteration[] = [];
    let currentIteration: Partial<ParsedIteration> | null = null;
    let iterationNumber = 0;

    // Track LLM requests for correlation
    const pendingRequests = new Map<string, {
      model: string;
      timestamp: Date;
    }>();

    for (const entry of this.rawEntries) {
      switch (entry._type) {
        case 'iteration.wrapper': {
          const wrapper = entry as IterationWrapperEntry;
          if (wrapper.phase === 'start') {
            iterationNumber = wrapper.iterationNumber;
            currentIteration = {
              number: iterationNumber,
              startTime: new Date(entry._ts),
              tools: [],
              decisions: [],
              metrics: {
                inputTokens: 0,
                outputTokens: 0,
                cacheHitRate: 0,
                toolCallCount: 0,
                cost: 0,
              },
            };
          } else if (wrapper.phase === 'end' && currentIteration) {
            currentIteration.endTime = new Date(entry._ts);
            currentIteration.durationMs = currentIteration.endTime.getTime() -
              (currentIteration.startTime?.getTime() || 0);
            if (wrapper.metrics) {
              currentIteration.metrics = {
                inputTokens: wrapper.metrics.inputTokens,
                outputTokens: wrapper.metrics.outputTokens,
                cacheHitRate: wrapper.metrics.cacheHitRate,
                toolCallCount: wrapper.metrics.toolCallCount,
                cost: wrapper.metrics.totalCost,
              };
            }
            iterations.push(currentIteration as ParsedIteration);
            currentIteration = null;
          }
          break;
        }

        case 'llm.request': {
          const req = entry as LLMRequestEntry;
          pendingRequests.set(req.requestId, {
            model: req.model,
            timestamp: new Date(entry._ts),
          });

          // Auto-create iteration if no wrapper
          if (!currentIteration) {
            iterationNumber++;
            currentIteration = {
              number: iterationNumber,
              startTime: new Date(entry._ts),
              tools: [],
              decisions: [],
              metrics: {
                inputTokens: 0,
                outputTokens: 0,
                cacheHitRate: 0,
                toolCallCount: 0,
                cost: 0,
              },
            };
          }
          break;
        }

        case 'llm.response': {
          const resp = entry as LLMResponseEntry;
          const request = pendingRequests.get(resp.requestId);
          pendingRequests.delete(resp.requestId);

          if (currentIteration) {
            currentIteration.llm = {
              requestId: resp.requestId,
              model: request?.model || 'unknown',
              inputTokens: resp.tokens.input,
              outputTokens: resp.tokens.output,
              cacheHitRate: resp.cache.hitRate,
              durationMs: resp.durationMs,
              content: '', // Would need full trace to get content
              toolCalls: [], // Would need full trace
            };
            currentIteration.metrics = {
              inputTokens: resp.tokens.input,
              outputTokens: resp.tokens.output,
              cacheHitRate: resp.cache.hitRate,
              toolCallCount: resp.toolCallCount,
              cost: 0, // Would need to calculate
            };
          }
          break;
        }

        case 'llm.thinking': {
          const thinking = entry as ThinkingEntry;
          if (currentIteration) {
            currentIteration.thinking = {
              content: thinking.thinking.content,
              estimatedTokens: thinking.thinking.estimatedTokens,
              summarized: thinking.thinking.summarized,
            };
          }
          break;
        }

        case 'tool.execution': {
          const tool = entry as ToolExecutionEntry;
          if (currentIteration && currentIteration.tools) {
            currentIteration.tools.push({
              executionId: tool.executionId,
              name: tool.toolName,
              arguments: {}, // Not captured in summary entry
              durationMs: tool.durationMs,
              status: tool.status as 'success' | 'error' | 'timeout' | 'blocked',
              resultSize: tool.resultSize,
              input: tool.input,
              outputPreview: tool.outputPreview,
              errorMessage: tool.errorMessage,
            });
          }
          break;
        }

        case 'decision': {
          const dec = entry as DecisionEntry;
          if (currentIteration && currentIteration.decisions) {
            currentIteration.decisions.push({
              type: dec.decision.type,
              decision: dec.decision.decision,
              outcome: dec.decision.outcome,
              reasoning: dec.decision.reasoning,
            });
          }
          break;
        }

        case 'session.end': {
          // Finalize any pending iteration
          if (currentIteration) {
            currentIteration.endTime = new Date(entry._ts);
            currentIteration.durationMs = currentIteration.endTime.getTime() -
              (currentIteration.startTime?.getTime() || 0);
            iterations.push(currentIteration as ParsedIteration);
            currentIteration = null;
          }
          break;
        }
      }
    }

    // Handle unclosed iteration
    if (currentIteration) {
      iterations.push(currentIteration as ParsedIteration);
    }

    return iterations;
  }

  /**
   * Calculate aggregated metrics from iterations.
   */
  private calculateMetrics(iterations: ParsedIteration[]): SessionMetrics {
    const toolNames = new Set<string>();
    let totalInputTokens = 0;
    let totalOutputTokens = 0;
    let totalThinkingTokens = 0;
    let totalCacheHitRate = 0;
    let totalCost = 0;
    let totalToolCalls = 0;
    let totalDecisions = 0;

    for (const iter of iterations) {
      totalInputTokens += iter.metrics.inputTokens;
      totalOutputTokens += iter.metrics.outputTokens;
      totalCacheHitRate += iter.metrics.cacheHitRate;
      totalCost += iter.metrics.cost;
      totalToolCalls += iter.tools.length;
      totalDecisions += iter.decisions.length;

      if (iter.thinking) {
        totalThinkingTokens += iter.thinking.estimatedTokens;
      }

      for (const tool of iter.tools) {
        toolNames.add(tool.name);
      }
    }

    const llmCalls = iterations.filter(i => i.llm).length;
    const avgCacheHitRate = iterations.length > 0
      ? totalCacheHitRate / iterations.length
      : 0;

    // Estimate cache savings (simplified)
    const tokensSavedByCache = Math.round(totalInputTokens * avgCacheHitRate);
    const costSavedByCache = tokensSavedByCache * 0.000003; // Rough estimate

    return {
      iterations: iterations.length,
      llmCalls,
      toolCalls: totalToolCalls,
      uniqueTools: toolNames.size,
      inputTokens: totalInputTokens,
      outputTokens: totalOutputTokens,
      thinkingTokens: totalThinkingTokens > 0 ? totalThinkingTokens : undefined,
      avgCacheHitRate,
      tokensSavedByCache,
      totalCost,
      costSavedByCache,
      errors: 0, // Calculated separately
      subagentSpawns: 0, // Calculated separately
      decisions: totalDecisions,
    };
  }

  /**
   * Get raw parsed events.
   */
  getEvents(): ParsedEvent[] {
    return this.events;
  }

  /**
   * Get raw trace entries.
   */
  getRawEntries(): TraceEntry[] {
    return this.rawEntries;
  }
}

/**
 * Factory function for creating a parser.
 */
export function createJSONLParser(): JSONLParser {
  return new JSONLParser();
}
