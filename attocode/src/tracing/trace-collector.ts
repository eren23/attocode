/**
 * Lesson 26: Trace Collector
 *
 * Central hub that coordinates tracing, metrics, and cache analysis.
 * Subscribes to agent events and produces comprehensive JSONL output.
 *
 * Key responsibilities:
 * 1. Capture full LLM request/response details
 * 2. Track tool execution with timing
 * 3. Analyze cache efficiency per request
 * 4. Export structured JSONL for analysis
 *
 * @example
 * ```typescript
 * const collector = new TraceCollector({
 *   outputDir: '.traces',
 *   captureMessageContent: true,
 * });
 *
 * collector.startSession('task-id', 'Write a fizzbuzz function', 'claude-3-sonnet');
 *
 * // During agent execution...
 * collector.recordLLMRequest(requestData);
 * collector.recordLLMResponse(responseData);
 * collector.recordToolExecution(toolData);
 *
 * // When done
 * const trace = await collector.endSession({ success: true });
 * ```
 */

import { mkdir, appendFile } from 'fs/promises';
import { join } from 'path';
import { Tracer, createTracer } from '../observability/tracer.js';
import { CacheBoundaryTracker, createCacheBoundaryTracker } from './cache-boundary-tracker.js';
import type {
  TraceCollectorConfig,
  SessionTrace,
  IterationTrace,
  LLMRequestTrace,
  ToolExecutionTrace,
  TracedMessage,
  TracedToolCall,
  TracedToolDefinition,
  TokenBreakdown,
  CacheBreakdown,
  JSONLEntry,
  SessionStartEntry,
  SessionEndEntry,
  TaskStartEntry,
  TaskEndEntry,
  TaskTrace,
  LLMRequestEntry,
  LLMResponseEntry,
  ToolExecutionEntry,
  ErrorEntry,
  // Enhanced trace types
  ThinkingBlock,
  ThinkingEntry,
  MemoryRetrievalTrace,
  MemoryRetrievalEntry,
  PlanEvolutionTrace,
  PlanEvolutionEntry,
  SubagentTraceLink,
  SubagentLinkEntry,
  DecisionTrace,
  DecisionEntry,
  IterationWrapperEntry,
  EnhancedTraceConfig,
} from './types.js';
import { DEFAULT_TRACE_CONFIG, DEFAULT_ENHANCED_TRACE_CONFIG } from './types.js';
import type { AgentMetrics, Span } from '../observability/types.js';
import { calculateCost as calculateOpenRouterCost } from '../integrations/openrouter-pricing.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Event types the collector can receive.
 */
export type TraceEvent =
  | { type: 'llm.request'; data: LLMRequestData }
  | { type: 'llm.response'; data: LLMResponseData }
  | { type: 'llm.thinking'; data: ThinkingData }
  | { type: 'tool.start'; data: ToolStartData }
  | { type: 'tool.end'; data: ToolEndData }
  | { type: 'iteration.start'; data: { iterationNumber: number } }
  | { type: 'iteration.end'; data: { iterationNumber: number } }
  | { type: 'memory.retrieval'; data: MemoryRetrievalData }
  | { type: 'plan.evolution'; data: PlanEvolutionData }
  | { type: 'subagent.link'; data: SubagentLinkData }
  | { type: 'decision'; data: DecisionData }
  | { type: 'error'; data: ErrorData };

/**
 * LLM request data.
 */
export interface LLMRequestData {
  requestId: string;
  model: string;
  provider: string;
  messages: Array<{
    role: 'system' | 'user' | 'assistant' | 'tool';
    content: string;
    toolCallId?: string;
    toolCalls?: TracedToolCall[];
  }>;
  tools?: Array<{
    name: string;
    description: string;
    parametersSchema: Record<string, unknown>;
  }>;
  parameters: {
    maxTokens?: number;
    temperature?: number;
    topP?: number;
    stopSequences?: string[];
  };
  systemPrompt?: string;
}

/**
 * LLM response data.
 */
export interface LLMResponseData {
  requestId: string;
  content: string;
  toolCalls?: TracedToolCall[];
  stopReason: 'end_turn' | 'tool_use' | 'max_tokens' | 'stop_sequence';
  usage: {
    inputTokens: number;
    outputTokens: number;
    cacheReadTokens?: number;
    cacheWriteTokens?: number;
    /** Actual cost from provider (e.g., OpenRouter returns this directly) */
    cost?: number;
  };
  durationMs: number;
}

/**
 * Tool start data.
 */
export interface ToolStartData {
  executionId: string;
  toolName: string;
  arguments: Record<string, unknown>;
}

/**
 * Tool end data.
 */
export interface ToolEndData {
  executionId: string;
  status: 'success' | 'error' | 'timeout' | 'blocked';
  result?: unknown;
  error?: Error;
  durationMs: number;
}

/**
 * Error data.
 */
export interface ErrorData {
  code: string;
  message: string;
  context: string;
  recoverable: boolean;
  error?: Error;
}

/**
 * LLM thinking data.
 */
export interface ThinkingData {
  /** Request ID this thinking belongs to */
  requestId: string;
  /** The thinking content */
  content: string;
  /** Whether this is summarized */
  summarized?: boolean;
  /** Original length if summarized */
  originalLength?: number;
  /** Thinking started timestamp */
  startTime?: number;
  /** Thinking duration in ms */
  durationMs?: number;
}

/**
 * Memory retrieval data.
 */
export interface MemoryRetrievalData {
  /** Query used for retrieval */
  query: string;
  /** Type of memory being retrieved */
  memoryType: 'conversation' | 'semantic' | 'episodic' | 'procedural' | 'external';
  /** Retrieved memories with relevance scores */
  results: Array<{
    id: string;
    content: string;
    relevance: number;
    source?: string;
    createdAt?: number;
  }>;
  /** Total memories considered */
  totalConsidered: number;
  /** Retrieval duration in ms */
  durationMs: number;
}

/**
 * Plan evolution data.
 */
export interface PlanEvolutionData {
  /** Plan version */
  version: number;
  /** Current plan state */
  plan: {
    goal: string;
    steps: Array<{
      id: string;
      description: string;
      status: 'pending' | 'in_progress' | 'completed' | 'failed' | 'skipped';
      dependencies?: string[];
    }>;
    progress: number;
  };
  /** What changed from previous version */
  change?: {
    type: 'created' | 'step_added' | 'step_removed' | 'step_modified' | 'step_completed' | 'step_failed' | 'replanned';
    reason: string;
    affectedSteps?: string[];
    previousState?: string;
  };
}

/**
 * Subagent link data.
 */
export interface SubagentLinkData {
  /** Parent session ID */
  parentSessionId: string;
  /** Child session ID */
  childSessionId: string;
  /** Child trace ID */
  childTraceId: string;
  /** Child agent configuration */
  childConfig: {
    agentType: string;
    model: string;
    task: string;
    tools?: string[];
  };
  /** Spawn context */
  spawnContext: {
    reason: string;
    expectedOutcome?: string;
    parentIteration: number;
  };
  /** Result summary (optional, filled when child completes) */
  result?: {
    success: boolean;
    summary: string;
    tokensUsed: number;
    durationMs: number;
  };
}

/**
 * Decision data.
 */
export interface DecisionData {
  /** Type of decision */
  type: 'routing' | 'tool_selection' | 'policy' | 'plan_choice' | 'model_selection' | 'retry' | 'escalation';
  /** The decision made */
  decision: string;
  /** Outcome/result of decision */
  outcome: 'allowed' | 'blocked' | 'modified' | 'deferred' | 'escalated';
  /** Reasoning behind decision */
  reasoning: string;
  /** Factors that influenced this decision */
  factors?: Array<{
    name: string;
    value: string | number | boolean;
    weight?: number;
  }>;
  /** Alternatives that were considered */
  alternatives?: Array<{
    option: string;
    reason: string;
    rejected: boolean;
  }>;
  /** Confidence in decision (0-1) */
  confidence?: number;
}

// =============================================================================
// TRACE COLLECTOR
// =============================================================================

/**
 * Subagent context for tagging events from child agents.
 * When a subagent shares its parent's trace collector, events are tagged
 * with this context so they can be aggregated in the parent's trace file.
 */
export interface SubagentContext {
  /** Parent's session ID (the trace file belongs to the parent) */
  parentSessionId: string;
  /** Type/name of this subagent (e.g., 'researcher', 'coder') */
  agentType: string;
  /** Iteration number in the parent when this subagent was spawned */
  spawnedAtIteration: number;
  /** Unique ID for this subagent instance */
  subagentId: string;
}

/**
 * Central trace collection hub.
 */
export class TraceCollector {
  private config: TraceCollectorConfig;
  private tracer: Tracer;
  private cacheTracker: CacheBoundaryTracker;

  // Session state
  private sessionId: string | null = null;
  private traceId: string | null = null;
  private task: string = '';
  private model: string = '';
  private startTime: number = 0;

  // Task-level state (for terminal sessions with multiple tasks)
  private currentTaskId: string | null = null;
  private currentTaskPrompt: string = '';
  private taskStartTime: number = 0;
  private taskNumber: number = 0;
  private taskIterations: IterationTrace[] = [];
  private allTasks: TaskTrace[] = [];

  // Last completed session (for retrieval after endSession)
  private lastCompletedSession: SessionTrace | null = null;

  // Current iteration state
  private currentIteration: number = 0;
  private iterationSpan: Span | null = null;
  private iterationStartTime: number = 0;
  private currentIterationTrace: Partial<IterationTrace> | null = null;

  // Accumulated data
  private iterations: IterationTrace[] = [];
  private pendingRequests: Map<string, { span: Span; data: LLMRequestData; startTime: number }> = new Map();
  private pendingTools: Map<string, { span: Span; data: ToolStartData; startTime: number }> = new Map();

  // JSONL output
  private outputPath: string | null = null;
  private writeQueue: Promise<void> = Promise.resolve();

  // Subagent context (set when this collector is shared with a subagent)
  private subagentContext: SubagentContext | null = null;

  constructor(config: Partial<TraceCollectorConfig> = {}) {
    this.config = { ...DEFAULT_TRACE_CONFIG, ...config };
    this.tracer = createTracer('trace-collector');
    this.cacheTracker = createCacheBoundaryTracker();
  }

  // Reference to parent collector (for subagent views to share write queue)
  private parentCollector: TraceCollector | null = null;

  /**
   * Create a subagent view of this trace collector.
   * The subagent will write to the same trace file, but events will be tagged
   * with the subagent context for proper aggregation.
   */
  createSubagentView(context: Omit<SubagentContext, 'subagentId'>): TraceCollector {
    const subagentId = `${context.agentType}-${context.spawnedAtIteration}`;
    const view = new TraceCollector(this.config);

    // Share the same output file and session state
    view.sessionId = this.sessionId;
    view.traceId = this.traceId;
    view.outputPath = this.outputPath;
    view.model = this.model;
    view.startTime = this.startTime;

    // Keep reference to parent for shared write queue
    view.parentCollector = this;

    // Set the subagent context for event tagging
    view.subagentContext = {
      ...context,
      subagentId,
    };

    return view;
  }

  // ===========================================================================
  // SESSION LIFECYCLE
  // ===========================================================================

  /**
   * Start a new tracing session.
   * For terminal sessions (REPL), task can be omitted - individual tasks are tracked via startTask/endTask.
   * For single-task sessions, task can be provided for backward compatibility.
   */
  async startSession(
    sessionId: string,
    task: string | undefined,
    model: string,
    metadata: Record<string, unknown> = {}
  ): Promise<void> {
    if (this.sessionId) {
      throw new Error('Session already in progress. Call endSession() first.');
    }

    this.sessionId = sessionId;
    this.task = task ?? '';
    this.model = model;
    this.startTime = Date.now();
    this.currentIteration = 0;
    this.iterations = [];
    this.taskNumber = 0;
    this.allTasks = [];
    this.cacheTracker.reset();

    // Start root span
    const rootSpan = this.tracer.startSpan('session', {
      kind: 'internal',
      attributes: {
        'session.id': sessionId,
        'session.task': task ?? 'terminal-session',
        'session.model': model,
      },
    });
    this.traceId = rootSpan.traceId;

    // Set up JSONL output
    if (this.config.enabled) {
      await this.initializeOutput();
      await this.writeEntry({
        _type: 'session.start',
        _ts: new Date().toISOString(),
        traceId: this.traceId,
        sessionId,
        task,
        model,
        metadata,
      } as SessionStartEntry);
    }
  }

  /**
   * End the current session and return the complete trace.
   */
  async endSession(result: {
    success: boolean;
    output?: string;
    failureReason?: string;
  }): Promise<SessionTrace> {
    if (!this.sessionId || !this.traceId) {
      throw new Error('No session in progress');
    }

    // End any pending task
    if (this.currentTaskId) {
      await this.endTask({ success: result.success, failureReason: result.failureReason });
    }

    const endTime = Date.now();
    const durationMs = endTime - this.startTime;

    // End any pending iteration
    if (this.iterationSpan) {
      this.tracer.endSpan(this.iterationSpan);
      this.iterationSpan = null;
    }

    // Calculate aggregated metrics
    const metrics = this.calculateAggregatedMetrics();

    // Build session trace
    const sessionTrace: SessionTrace = {
      sessionId: this.sessionId,
      traceId: this.traceId,
      task: this.task,
      model: this.model,
      startTime: this.startTime,
      endTime,
      durationMs,
      status: result.success ? 'completed' : 'failed',
      iterations: this.iterations,
      metrics,
      result,
      metadata: {},
    };

    // Write session end entry
    if (this.config.enabled) {
      await this.writeEntry({
        _type: 'session.end',
        _ts: new Date().toISOString(),
        traceId: this.traceId,
        sessionId: this.sessionId,
        status: sessionTrace.status,
        durationMs,
        metrics: {
          inputTokens: metrics.inputTokens,
          outputTokens: metrics.outputTokens,
          cacheReadTokens: metrics.cacheReadTokens,
          cacheWriteTokens: metrics.cacheWriteTokens,
          estimatedCost: metrics.estimatedCost,
          toolCalls: metrics.toolCalls,
          llmCalls: metrics.llmCalls,
          duration: durationMs,
          errors: metrics.errors,
          retries: metrics.retries,
        },
      } as SessionEndEntry);

      await this.flush();
    }

    // Store completed session before resetting state
    // This allows getSessionTrace() to return data after session ends
    this.lastCompletedSession = sessionTrace;

    // Reset state
    this.sessionId = null;
    this.traceId = null;
    this.task = '';
    this.model = '';
    this.currentTaskId = null;
    this.currentTaskPrompt = '';
    this.taskNumber = 0;
    this.allTasks = [];

    return sessionTrace;
  }

  // ===========================================================================
  // TASK LIFECYCLE (for terminal sessions with multiple tasks)
  // ===========================================================================

  /**
   * Start a new task within the current session.
   * Use this for terminal sessions where each user prompt is a separate task.
   */
  async startTask(taskId: string, prompt: string): Promise<void> {
    if (!this.sessionId || !this.traceId) {
      throw new Error('No session in progress. Call startSession() first.');
    }

    // End any previous task
    if (this.currentTaskId) {
      await this.endTask({ success: true });
    }

    this.currentTaskId = taskId;
    this.currentTaskPrompt = prompt;
    this.taskStartTime = Date.now();
    this.taskNumber++;
    this.taskIterations = [];
    this.currentIteration = 0;

    // Write task start entry
    if (this.config.enabled) {
      await this.writeEntry({
        _type: 'task.start',
        _ts: new Date().toISOString(),
        traceId: this.traceId,
        taskId,
        sessionId: this.sessionId,
        prompt,
        taskNumber: this.taskNumber,
      } as TaskStartEntry);
    }
  }

  /**
   * End the current task within the session.
   */
  async endTask(result: {
    success: boolean;
    output?: string;
    failureReason?: string;
  }): Promise<TaskTrace | null> {
    if (!this.currentTaskId || !this.sessionId || !this.traceId) {
      return null;
    }

    const endTime = Date.now();
    const durationMs = endTime - this.taskStartTime;

    // End any pending iteration
    if (this.iterationSpan) {
      this.tracer.endSpan(this.iterationSpan);
      this.iterationSpan = null;
    }

    // Calculate task metrics from task iterations
    const metrics = this.calculateTaskMetrics();

    // Build task trace
    const taskTrace: TaskTrace = {
      taskId: this.currentTaskId,
      sessionId: this.sessionId,
      traceId: this.traceId,
      prompt: this.currentTaskPrompt,
      startTime: this.taskStartTime,
      endTime,
      durationMs,
      status: result.success ? 'completed' : 'failed',
      taskNumber: this.taskNumber,
      iterations: [...this.taskIterations],
      metrics,
      result,
    };

    // Write task end entry
    if (this.config.enabled) {
      await this.writeEntry({
        _type: 'task.end',
        _ts: new Date().toISOString(),
        traceId: this.traceId,
        taskId: this.currentTaskId,
        sessionId: this.sessionId,
        status: taskTrace.status,
        durationMs,
        metrics,
        result,
      } as TaskEndEntry);
    }

    // Store in all tasks
    this.allTasks.push(taskTrace);

    // Move task iterations to session iterations
    this.iterations.push(...this.taskIterations);

    // Reset task state
    this.currentTaskId = null;
    this.currentTaskPrompt = '';
    this.taskIterations = [];

    return taskTrace;
  }

  /**
   * Check if a task is currently active.
   */
  isTaskActive(): boolean {
    return this.currentTaskId !== null;
  }

  /**
   * Get current task ID.
   */
  getCurrentTaskId(): string | null {
    return this.currentTaskId;
  }

  /**
   * Calculate metrics for the current task.
   */
  private calculateTaskMetrics(): TaskTrace['metrics'] {
    let inputTokens = 0;
    let outputTokens = 0;
    let totalCacheHitRate = 0;
    let toolCalls = 0;
    let totalCost = 0;

    for (const iteration of this.taskIterations) {
      inputTokens += iteration.metrics.inputTokens;
      outputTokens += iteration.metrics.outputTokens;
      totalCacheHitRate += iteration.metrics.cacheHitRate;
      toolCalls += iteration.metrics.toolCallCount;
      totalCost += iteration.metrics.totalCost;
    }

    const cacheHitRate = this.taskIterations.length > 0
      ? totalCacheHitRate / this.taskIterations.length
      : 0;

    return {
      inputTokens,
      outputTokens,
      cacheHitRate,
      toolCalls,
      totalCost,
    };
  }

  // ===========================================================================
  // EVENT RECORDING
  // ===========================================================================

  /**
   * Record an event.
   */
  async record(event: TraceEvent): Promise<void> {
    if (!this.config.enabled || !this.sessionId) return;

    switch (event.type) {
      case 'llm.request':
        await this.recordLLMRequest(event.data);
        break;
      case 'llm.response':
        await this.recordLLMResponse(event.data);
        break;
      case 'llm.thinking':
        await this.recordThinking(event.data);
        break;
      case 'tool.start':
        await this.recordToolStart(event.data);
        break;
      case 'tool.end':
        await this.recordToolEnd(event.data);
        break;
      case 'iteration.start':
        this.startIteration(event.data.iterationNumber);
        break;
      case 'iteration.end':
        await this.endIteration();
        break;
      case 'memory.retrieval':
        await this.recordMemoryRetrieval(event.data);
        break;
      case 'plan.evolution':
        await this.recordPlanEvolution(event.data);
        break;
      case 'subagent.link':
        await this.recordSubagentLink(event.data);
        break;
      case 'decision':
        await this.recordDecision(event.data);
        break;
      case 'error':
        await this.recordError(event.data);
        break;
    }
  }

  /**
   * Record an LLM request.
   */
  private async recordLLMRequest(data: LLMRequestData): Promise<void> {
    const span = this.tracer.startSpan('llm.request', {
      kind: 'client',
      attributes: {
        'llm.model': data.model,
        'llm.provider': data.provider,
        'llm.message_count': data.messages.length,
        'llm.tool_count': data.tools?.length ?? 0,
      },
    });

    // Track cache boundaries
    if (this.config.analyzeCacheBoundaries) {
      this.cacheTracker.recordRequest({
        systemPrompt: data.systemPrompt ?? data.messages.find(m => m.role === 'system')?.content ?? '',
        messages: data.messages,
        toolDefinitions: data.tools,
      });
    }

    // Store pending request
    this.pendingRequests.set(data.requestId, {
      span,
      data,
      startTime: Date.now(),
    });

    // Estimate input tokens
    const estimatedInputTokens = this.estimateInputTokens(data);

    // Write JSONL entry
    await this.writeEntry({
      _type: 'llm.request',
      _ts: new Date().toISOString(),
      traceId: this.traceId!,
      requestId: data.requestId,
      model: data.model,
      messageCount: data.messages.length,
      toolCount: data.tools?.length ?? 0,
      estimatedInputTokens,
    } as LLMRequestEntry);
  }

  /**
   * Record an LLM response.
   */
  private async recordLLMResponse(data: LLMResponseData): Promise<void> {
    const pending = this.pendingRequests.get(data.requestId);
    if (!pending) {
      console.warn(`No pending request found for ${data.requestId}`);
      return;
    }

    const { span, data: requestData, startTime } = pending;
    this.pendingRequests.delete(data.requestId);

    // Update cache tracker with actual API response
    let cacheBreakdown: CacheBreakdown;
    if (this.config.analyzeCacheBoundaries && data.usage.cacheReadTokens !== undefined) {
      cacheBreakdown = this.cacheTracker.recordResponse({
        cacheReadTokens: data.usage.cacheReadTokens,
        cacheWriteTokens: data.usage.cacheWriteTokens ?? 0,
        totalInputTokens: data.usage.inputTokens,
        outputTokens: data.usage.outputTokens,
      });
    } else {
      cacheBreakdown = {
        cacheReadTokens: data.usage.cacheReadTokens ?? 0,
        cacheWriteTokens: data.usage.cacheWriteTokens ?? 0,
        freshTokens: data.usage.inputTokens - (data.usage.cacheReadTokens ?? 0),
        hitRate: data.usage.cacheReadTokens
          ? data.usage.cacheReadTokens / data.usage.inputTokens
          : 0,
        estimatedSavings: 0,
        breakpoints: [],
      };
    }

    // Calculate token breakdown
    const tokens: TokenBreakdown = {
      input: data.usage.inputTokens,
      output: data.usage.outputTokens,
      total: data.usage.inputTokens + data.usage.outputTokens,
      breakdown: {
        systemPrompt: this.estimateTokens(requestData.systemPrompt ?? ''),
        messages: data.usage.inputTokens - this.estimateTokens(requestData.systemPrompt ?? ''),
        toolDefinitions: requestData.tools ? this.estimateToolTokens(requestData.tools) : 0,
        toolResults: 0,
      },
    };

    // Build LLM request trace
    const llmTrace: LLMRequestTrace = {
      requestId: data.requestId,
      traceId: this.traceId!,
      spanId: span.spanId,
      timestamp: startTime,
      durationMs: data.durationMs,
      model: requestData.model,
      provider: requestData.provider,
      request: {
        messages: this.config.captureMessageContent
          ? this.traceMessages(requestData.messages)
          : [],
        tools: requestData.tools?.map(t => ({
          name: t.name,
          description: t.description,
          parametersSchema: t.parametersSchema,
          estimatedTokens: this.estimateTokens(JSON.stringify(t)),
        })),
        parameters: requestData.parameters,
      },
      response: {
        content: this.config.captureMessageContent ? data.content : '[content not captured]',
        toolCalls: data.toolCalls,
        stopReason: data.stopReason,
      },
      tokens,
      cache: cacheBreakdown,
      // Store actual cost from provider (e.g., OpenRouter) when available
      actualCost: data.usage.cost,
    };

    // Store in current iteration
    if (this.currentIterationTrace) {
      this.currentIterationTrace.llmRequest = llmTrace;
    }

    // Update span
    this.tracer.setAttributes(span, {
      'llm.input_tokens': data.usage.inputTokens,
      'llm.output_tokens': data.usage.outputTokens,
      'llm.cache_read_tokens': data.usage.cacheReadTokens ?? 0,
      'llm.cache_hit_rate': cacheBreakdown.hitRate,
      'llm.stop_reason': data.stopReason,
      'llm.tool_calls': data.toolCalls?.length ?? 0,
    });
    this.tracer.endSpan(span);

    // Write JSONL entry
    await this.writeEntry({
      _type: 'llm.response',
      _ts: new Date().toISOString(),
      traceId: this.traceId!,
      requestId: data.requestId,
      durationMs: data.durationMs,
      tokens,
      cache: cacheBreakdown,
      stopReason: data.stopReason,
      toolCallCount: data.toolCalls?.length ?? 0,
    } as LLMResponseEntry);
  }

  /**
   * Record tool execution start.
   */
  private async recordToolStart(data: ToolStartData): Promise<void> {
    const span = this.tracer.startSpan(`tool.${data.toolName}`, {
      kind: 'internal',
      attributes: {
        'tool.name': data.toolName,
        'tool.execution_id': data.executionId,
      },
    });

    this.pendingTools.set(data.executionId, {
      span,
      data,
      startTime: Date.now(),
    });
  }

  /**
   * Record tool execution end.
   */
  private async recordToolEnd(data: ToolEndData): Promise<void> {
    const pending = this.pendingTools.get(data.executionId);
    if (!pending) {
      console.warn(`No pending tool execution found for ${data.executionId}`);
      return;
    }

    const { span, data: startData, startTime } = pending;
    this.pendingTools.delete(data.executionId);

    // Build tool trace
    const toolTrace: ToolExecutionTrace = {
      executionId: data.executionId,
      traceId: this.traceId!,
      spanId: span.spanId,
      toolName: startData.toolName,
      arguments: startData.arguments,
      startTime,
      durationMs: data.durationMs,
      status: data.status,
    };

    // Add result or error
    if (data.status === 'success' && data.result !== undefined) {
      const resultStr = typeof data.result === 'string'
        ? data.result
        : JSON.stringify(data.result);

      toolTrace.result = {
        type: typeof data.result === 'string' ? 'string' : 'object',
        value: this.config.captureToolResults
          ? this.truncateResult(data.result)
          : '[result not captured]',
        truncated: resultStr.length > this.config.maxResultSize,
        originalSize: resultStr.length,
      };
    }

    if (data.error) {
      toolTrace.error = {
        name: data.error.name,
        message: data.error.message,
        stack: data.error.stack,
      };
    }

    // Store in current iteration
    if (this.currentIterationTrace) {
      if (!this.currentIterationTrace.toolExecutions) {
        this.currentIterationTrace.toolExecutions = [];
      }
      this.currentIterationTrace.toolExecutions.push(toolTrace);
    }

    // Update span
    this.tracer.setAttributes(span, {
      'tool.status': data.status,
      'tool.duration_ms': data.durationMs,
    });

    if (data.status === 'error') {
      this.tracer.setError(span, data.error ?? new Error('Unknown error'));
    }

    this.tracer.endSpan(span, {
      code: data.status === 'success' ? 'ok' : 'error',
      message: data.status === 'error' ? data.error?.message : undefined,
    });

    // Write JSONL entry with input/output details
    const entry: ToolExecutionEntry = {
      _type: 'tool.execution',
      _ts: new Date().toISOString(),
      traceId: this.traceId!,
      executionId: data.executionId,
      toolName: startData.toolName,
      durationMs: data.durationMs,
      status: data.status,
      resultSize: toolTrace.result?.originalSize,
      input: this.truncateInput(startData.arguments, startData.toolName),
      outputPreview: this.getOutputPreview(data.result, data.status),
      errorMessage: data.status === 'error' ? data.error?.message : undefined,
    };
    await this.writeEntry(entry);
  }

  /**
   * Truncate tool input for trace logging.
   * Shows key arguments but limits large values.
   */
  private truncateInput(
    args: Record<string, unknown>,
    toolName: string
  ): Record<string, unknown> {
    const MAX_STRING_LENGTH = 200;
    const result: Record<string, unknown> = {};

    for (const [key, value] of Object.entries(args)) {
      if (typeof value === 'string') {
        // For file paths, show full path
        if (key === 'path' || key === 'file_path' || key === 'directory') {
          result[key] = value;
        } else if (key === 'command' && toolName === 'bash') {
          // Show bash commands (truncated if very long)
          result[key] = value.length > 500 ? value.slice(0, 500) + '...' : value;
        } else if (key === 'content' || key === 'new_content') {
          // Truncate file content
          result[key] = value.length > MAX_STRING_LENGTH
            ? `${value.slice(0, MAX_STRING_LENGTH)}... (${value.length} chars)`
            : value;
        } else {
          result[key] = value.length > MAX_STRING_LENGTH
            ? value.slice(0, MAX_STRING_LENGTH) + '...'
            : value;
        }
      } else if (typeof value === 'object' && value !== null) {
        // Show structure but truncate nested values
        const str = JSON.stringify(value);
        result[key] = str.length > MAX_STRING_LENGTH
          ? `${str.slice(0, MAX_STRING_LENGTH)}...`
          : value;
      } else {
        result[key] = value;
      }
    }

    return result;
  }

  /**
   * Get a preview of the tool output.
   */
  private getOutputPreview(result: unknown, status: string): string | undefined {
    if (status === 'error' || status === 'blocked' || status === 'timeout') {
      return undefined;
    }

    if (result === undefined || result === null) {
      return undefined;
    }

    const MAX_PREVIEW_LENGTH = 300;
    let preview: string;

    if (typeof result === 'string') {
      preview = result;
    } else {
      try {
        preview = JSON.stringify(result);
      } catch {
        preview = String(result);
      }
    }

    if (preview.length > MAX_PREVIEW_LENGTH) {
      return preview.slice(0, MAX_PREVIEW_LENGTH) + '...';
    }

    return preview;
  }

  /**
   * Record an error.
   */
  private async recordError(data: ErrorData): Promise<void> {
    await this.writeEntry({
      _type: 'error',
      _ts: new Date().toISOString(),
      traceId: this.traceId!,
      errorCode: data.code,
      errorMessage: data.message,
      context: data.context,
      recoverable: data.recoverable,
    } as ErrorEntry);
  }

  // ===========================================================================
  // ENHANCED TRACE RECORDING (Maximum Interpretability)
  // ===========================================================================

  /**
   * Record LLM thinking/reasoning blocks.
   */
  private async recordThinking(data: ThinkingData): Promise<void> {
    const thinkingId = `think-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

    const thinking: ThinkingBlock = {
      id: thinkingId,
      content: data.content,
      estimatedTokens: this.estimateTokens(data.content),
      summarized: data.summarized ?? false,
      originalLength: data.originalLength,
      startTime: data.startTime ?? Date.now(),
      durationMs: data.durationMs,
    };

    await this.writeEntry({
      _type: 'llm.thinking',
      _ts: new Date().toISOString(),
      traceId: this.traceId!,
      requestId: data.requestId,
      thinking,
    } as ThinkingEntry);
  }

  /**
   * Record memory retrieval events.
   */
  private async recordMemoryRetrieval(data: MemoryRetrievalData): Promise<void> {
    const retrievalId = `ret-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

    const retrieval: MemoryRetrievalTrace = {
      retrievalId,
      traceId: this.traceId!,
      query: data.query,
      memoryType: data.memoryType,
      results: data.results,
      totalConsidered: data.totalConsidered,
      durationMs: data.durationMs,
      timestamp: Date.now(),
    };

    await this.writeEntry({
      _type: 'memory.retrieval',
      _ts: new Date().toISOString(),
      traceId: this.traceId!,
      retrieval,
    } as MemoryRetrievalEntry);
  }

  /**
   * Record plan evolution events.
   */
  private async recordPlanEvolution(data: PlanEvolutionData): Promise<void> {
    const evolution: PlanEvolutionTrace = {
      version: data.version,
      traceId: this.traceId!,
      plan: data.plan,
      change: data.change,
      timestamp: Date.now(),
    };

    await this.writeEntry({
      _type: 'plan.evolution',
      _ts: new Date().toISOString(),
      traceId: this.traceId!,
      evolution,
    } as PlanEvolutionEntry);
  }

  /**
   * Record subagent spawn/completion events.
   */
  private async recordSubagentLink(data: SubagentLinkData): Promise<void> {
    const link: SubagentTraceLink = {
      parentTraceId: this.traceId!,
      parentSessionId: data.parentSessionId,
      childTraceId: data.childTraceId,
      childSessionId: data.childSessionId,
      childConfig: data.childConfig,
      spawnContext: data.spawnContext,
      result: data.result,
      spawnedAt: Date.now(),
      completedAt: data.result ? Date.now() : undefined,
    };

    await this.writeEntry({
      _type: 'subagent.link',
      _ts: new Date().toISOString(),
      traceId: this.traceId!,
      link,
    } as SubagentLinkEntry);
  }

  /**
   * Record decision events.
   */
  private async recordDecision(data: DecisionData): Promise<void> {
    const decisionId = `dec-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

    const decision: DecisionTrace = {
      decisionId,
      traceId: this.traceId!,
      type: data.type,
      decision: data.decision,
      outcome: data.outcome,
      reasoning: data.reasoning,
      factors: data.factors ?? [],
      alternatives: data.alternatives,
      confidence: data.confidence,
      timestamp: Date.now(),
    };

    await this.writeEntry({
      _type: 'decision',
      _ts: new Date().toISOString(),
      traceId: this.traceId!,
      decision,
    } as DecisionEntry);
  }

  // ===========================================================================
  // ITERATION MANAGEMENT
  // ===========================================================================

  /**
   * Start a new iteration.
   */
  private startIteration(iterationNumber: number): void {
    this.currentIteration = iterationNumber;
    this.iterationStartTime = Date.now();

    this.iterationSpan = this.tracer.startSpan(`iteration.${iterationNumber}`, {
      kind: 'internal',
      attributes: {
        'iteration.number': iterationNumber,
      },
    });

    this.currentIterationTrace = {
      iterationNumber,
      traceId: this.traceId!,
      spanId: this.iterationSpan.spanId,
      startTime: this.iterationStartTime,
      toolExecutions: [],
    };
  }

  /**
   * End the current iteration.
   */
  private async endIteration(): Promise<void> {
    if (!this.iterationSpan || !this.currentIterationTrace) return;

    const endTime = Date.now();
    const durationMs = endTime - this.iterationStartTime;

    // Calculate iteration metrics
    const llmRequest = this.currentIterationTrace.llmRequest;
    // Use actual cost from provider if available, otherwise calculate
    const actualCost = llmRequest?.actualCost;
    const calculatedCost = this.calculateCost(
      llmRequest?.tokens.input ?? 0,
      llmRequest?.tokens.output ?? 0,
      llmRequest?.cache.cacheReadTokens ?? 0
    );

    const metrics = {
      inputTokens: llmRequest?.tokens.input ?? 0,
      outputTokens: llmRequest?.tokens.output ?? 0,
      cacheHitRate: llmRequest?.cache.hitRate ?? 0,
      toolCallCount: this.currentIterationTrace.toolExecutions?.length ?? 0,
      totalCost: actualCost ?? calculatedCost,
    };

    // Complete iteration trace
    const iterationTrace: IterationTrace = {
      ...this.currentIterationTrace as IterationTrace,
      durationMs,
      metrics,
    };

    // If a task is active, store in task iterations (will be moved to session iterations when task ends)
    // Otherwise, store directly in session iterations (backward compatibility)
    if (this.currentTaskId) {
      this.taskIterations.push(iterationTrace);
    } else {
      this.iterations.push(iterationTrace);
    }

    // End span
    this.tracer.setAttributes(this.iterationSpan, {
      'iteration.duration_ms': durationMs,
      'iteration.input_tokens': metrics.inputTokens,
      'iteration.output_tokens': metrics.outputTokens,
      'iteration.cache_hit_rate': metrics.cacheHitRate,
      'iteration.tool_calls': metrics.toolCallCount,
    });
    this.tracer.endSpan(this.iterationSpan);

    this.iterationSpan = null;
    this.currentIterationTrace = null;
  }

  // ===========================================================================
  // JSONL OUTPUT
  // ===========================================================================

  /**
   * Initialize output file.
   */
  private async initializeOutput(): Promise<void> {
    if (!this.config.outputDir) return;

    await mkdir(this.config.outputDir, { recursive: true });

    const filename = this.config.filePattern
      .replace('{sessionId}', this.sessionId ?? 'unknown')
      .replace('{timestamp}', Date.now().toString());

    this.outputPath = join(this.config.outputDir, filename);
  }

  /**
   * Write a JSONL entry.
   * If this is a subagent view, entries are enriched with subagent context
   * and written using the parent's write queue to avoid race conditions.
   */
  private async writeEntry(entry: JSONLEntry): Promise<void> {
    if (!this.outputPath) return;

    // Enrich entry with subagent context if present
    const enrichedEntry = this.subagentContext
      ? {
          ...entry,
          subagentId: this.subagentContext.subagentId,
          subagentType: this.subagentContext.agentType,
          parentSessionId: this.subagentContext.parentSessionId,
          spawnedAtIteration: this.subagentContext.spawnedAtIteration,
        }
      : entry;

    // If this is a subagent view, delegate to parent's write queue
    // to ensure all writes to the same file are serialized
    if (this.parentCollector) {
      await this.parentCollector.writeEntryDirect(enrichedEntry);
      return;
    }

    // Queue writes to avoid race conditions
    this.writeQueue = this.writeQueue.then(async () => {
      try {
        await appendFile(this.outputPath!, JSON.stringify(enrichedEntry) + '\n');
      } catch (err) {
        console.error('Failed to write trace entry:', err);
      }
    });
  }

  /**
   * Direct write entry method for subagent views to use parent's write queue.
   * @internal
   */
  private async writeEntryDirect(entry: JSONLEntry): Promise<void> {
    if (!this.outputPath) return;

    this.writeQueue = this.writeQueue.then(async () => {
      try {
        await appendFile(this.outputPath!, JSON.stringify(entry) + '\n');
      } catch (err) {
        console.error('Failed to write trace entry:', err);
      }
    });
  }

  /**
   * Flush pending writes.
   * If this is a subagent view, flushes the parent's write queue.
   */
  async flush(): Promise<void> {
    if (this.parentCollector) {
      await this.parentCollector.flush();
    } else {
      await this.writeQueue;
    }
  }

  // ===========================================================================
  // HELPER METHODS
  // ===========================================================================

  /**
   * Convert messages to traced format.
   */
  private traceMessages(messages: LLMRequestData['messages']): TracedMessage[] {
    return messages.map(msg => ({
      role: msg.role,
      content: msg.content,
      estimatedTokens: this.estimateTokens(msg.content),
      toolCallId: msg.toolCallId,
      toolCalls: msg.toolCalls,
      contentHash: this.hashContent(msg.content),
    }));
  }

  /**
   * Estimate tokens from text.
   */
  private estimateTokens(text: string): number {
    return Math.ceil(text.length / 4);
  }

  /**
   * Estimate input tokens for a request.
   */
  private estimateInputTokens(data: LLMRequestData): number {
    let tokens = 0;
    for (const msg of data.messages) {
      tokens += this.estimateTokens(msg.content);
    }
    if (data.tools) {
      tokens += this.estimateToolTokens(data.tools);
    }
    return tokens;
  }

  /**
   * Estimate tokens for tool definitions.
   */
  private estimateToolTokens(tools: NonNullable<LLMRequestData['tools']>): number {
    let tokens = 0;
    for (const tool of tools) {
      tokens += this.estimateTokens(tool.name);
      tokens += this.estimateTokens(tool.description);
      tokens += this.estimateTokens(JSON.stringify(tool.parametersSchema));
    }
    return tokens;
  }

  /**
   * Truncate result if too large.
   */
  private truncateResult(result: unknown): unknown {
    const str = typeof result === 'string' ? result : JSON.stringify(result);
    if (str.length <= this.config.maxResultSize) {
      return result;
    }
    return str.substring(0, this.config.maxResultSize) + '... [truncated]';
  }

  /**
   * Calculate cost for tokens using OpenRouter pricing data.
   * Falls back to reasonable defaults if model not found.
   */
  private calculateCost(inputTokens: number, outputTokens: number, cachedTokens: number): number {
    // Use OpenRouter pricing (fetched from API or defaults)
    // Note: OpenRouter pricing doesn't have separate cached pricing,
    // so we treat cached tokens as ~10x cheaper (standard cache discount)

    // Calculate full cost using OpenRouter pricing
    const fullCost = calculateOpenRouterCost(this.model, inputTokens, outputTokens);

    // Apply cache discount: cached tokens cost ~10% of regular input
    // fullCost = (input * inputPrice) + (output * outputPrice)
    // We need to subtract the savings from cached tokens
    const inputPricePerToken = inputTokens > 0 ?
      (fullCost - calculateOpenRouterCost(this.model, 0, outputTokens)) / inputTokens : 0;
    const cacheSavings = cachedTokens * inputPricePerToken * 0.9; // 90% discount

    return Math.max(0, fullCost - cacheSavings);
  }

  /**
   * Simple content hash.
   */
  private hashContent(content: string): string {
    let hash = 0;
    for (let i = 0; i < content.length; i++) {
      const char = content.charCodeAt(i);
      hash = ((hash << 5) - hash) + char;
      hash = hash & hash;
    }
    return hash.toString(16);
  }

  /**
   * Calculate aggregated metrics across all iterations.
   */
  private calculateAggregatedMetrics(): SessionTrace['metrics'] {
    let inputTokens = 0;
    let outputTokens = 0;
    let cacheReadTokens = 0;
    let cacheWriteTokens = 0;
    let estimatedCost = 0;
    let toolCalls = 0;
    let totalCacheHitRate = 0;
    let tokensSavedByCache = 0;

    for (const iteration of this.iterations) {
      inputTokens += iteration.metrics.inputTokens;
      outputTokens += iteration.metrics.outputTokens;
      cacheReadTokens += iteration.llmRequest?.cache.cacheReadTokens ?? 0;
      cacheWriteTokens += iteration.llmRequest?.cache.cacheWriteTokens ?? 0;
      estimatedCost += iteration.metrics.totalCost;
      toolCalls += iteration.metrics.toolCallCount;
      totalCacheHitRate += iteration.metrics.cacheHitRate;
    }

    const llmCalls = this.iterations.length;
    const avgCacheHitRate = llmCalls > 0 ? totalCacheHitRate / llmCalls : 0;

    // Cost saved by caching
    const costWithoutCache = this.calculateCost(inputTokens, outputTokens, 0);
    const costSavedByCache = costWithoutCache - estimatedCost;
    tokensSavedByCache = cacheReadTokens; // Tokens that would have been re-sent

    return {
      inputTokens,
      outputTokens,
      cacheReadTokens,
      cacheWriteTokens,
      estimatedCost,
      toolCalls,
      llmCalls,
      duration: Date.now() - this.startTime,
      errors: 0, // TODO: track errors
      retries: 0, // TODO: track retries
      avgCacheHitRate,
      tokensSavedByCache,
      costSavedByCache,
    };
  }

  // ===========================================================================
  // PUBLIC ACCESSORS
  // ===========================================================================

  /**
   * Get the underlying tracer.
   */
  getTracer(): Tracer {
    return this.tracer;
  }

  /**
   * Get the cache tracker.
   */
  getCacheTracker(): CacheBoundaryTracker {
    return this.cacheTracker;
  }

  /**
   * Get current session ID.
   */
  getSessionId(): string | null {
    return this.sessionId;
  }

  /**
   * Get current trace ID.
   */
  getTraceId(): string | null {
    return this.traceId;
  }

  /**
   * Check if a session is active.
   */
  isSessionActive(): boolean {
    return this.sessionId !== null;
  }

  /**
   * Get iteration count.
   */
  getIterationCount(): number {
    return this.iterations.length;
  }

  /**
   * Get the output file path for this trace.
   */
  getOutputPath(): string | null {
    return this.outputPath;
  }

  /**
   * Get the subagent context if this is a subagent view.
   */
  getSubagentContext(): SubagentContext | null {
    return this.subagentContext;
  }

  /**
   * Check if this is a subagent view.
   */
  isSubagentView(): boolean {
    return this.subagentContext !== null;
  }

  /**
   * Get the current session trace without ending the session.
   * If no session is active, returns the last completed session.
   * Returns null if no session data is available.
   */
  getSessionTrace(): SessionTrace | null {
    // If there's an active session, return its current state
    if (this.sessionId && this.traceId) {
      const metrics = this.calculateAggregatedMetrics();

      return {
        sessionId: this.sessionId,
        traceId: this.traceId,
        task: this.task,
        model: this.model,
        startTime: this.startTime,
        endTime: Date.now(),
        durationMs: Date.now() - this.startTime,
        status: 'running',
        iterations: [...this.iterations], // Copy to avoid mutation
        metrics,
        result: { success: true }, // Placeholder for in-progress session
        metadata: {},
      };
    }

    // Otherwise return the last completed session
    return this.lastCompletedSession;
  }

  /**
   * Parse the current JSONL trace file and aggregate subagent metrics.
   * Returns hierarchical view of all agents with their metrics.
   */
  async getSubagentHierarchy(): Promise<SubagentHierarchy | null> {
    if (!this.outputPath) {
      return null;
    }

    try {
      const { readFile } = await import('fs/promises');
      const content = await readFile(this.outputPath, 'utf-8');
      const lines = content.trim().split('\n').filter(line => line.length > 0);

      // Parse all entries
      const entries = lines.map(line => {
        try {
          return JSON.parse(line) as JSONLEntry & {
            subagentId?: string;
            subagentType?: string;
            parentSessionId?: string;
            spawnedAtIteration?: number;
          };
        } catch {
          return null;
        }
      }).filter((e): e is NonNullable<typeof e> => e !== null);

      // Group by agent (null = main agent, string = subagent)
      const mainAgent: AgentMetricsData = {
        agentId: 'main',
        agentType: 'main',
        inputTokens: 0,
        outputTokens: 0,
        toolCalls: 0,
        llmCalls: 0,
        estimatedCost: 0,
        duration: 0,
        startTime: 0,
        endTime: 0,
      };

      const subagents = new Map<string, AgentMetricsData>();

      for (const entry of entries) {
        const isSubagent = entry.subagentId !== undefined;
        let target: AgentMetricsData;

        if (isSubagent) {
          if (!subagents.has(entry.subagentId!)) {
            subagents.set(entry.subagentId!, {
              agentId: entry.subagentId!,
              agentType: entry.subagentType!,
              parentSessionId: entry.parentSessionId,
              spawnedAtIteration: entry.spawnedAtIteration,
              inputTokens: 0,
              outputTokens: 0,
              toolCalls: 0,
              llmCalls: 0,
              estimatedCost: 0,
              duration: 0,
              startTime: 0,
              endTime: 0,
            });
          }
          target = subagents.get(entry.subagentId!)!;
        } else {
          target = mainAgent;
        }

        // Aggregate metrics based on entry type
        if (entry._type === 'llm.response') {
          const resp = entry as LLMResponseEntry;
          target.inputTokens += resp.tokens?.input ?? 0;
          target.outputTokens += resp.tokens?.output ?? 0;
          target.llmCalls++;
        } else if (entry._type === 'tool.execution') {
          target.toolCalls++;
        } else if (entry._type === 'session.start') {
          if (!isSubagent) {
            mainAgent.startTime = new Date(entry._ts).getTime();
          }
        } else if (entry._type === 'session.end') {
          if (!isSubagent) {
            mainAgent.endTime = new Date(entry._ts).getTime();
            const sessionEnd = entry as SessionEndEntry;
            mainAgent.estimatedCost = sessionEnd.metrics?.estimatedCost ?? 0;
          }
        }

        // Track timing
        const ts = new Date(entry._ts).getTime();
        if (target.startTime === 0 || ts < target.startTime) {
          target.startTime = ts;
        }
        if (ts > target.endTime) {
          target.endTime = ts;
        }
      }

      // Calculate durations
      mainAgent.duration = mainAgent.endTime - mainAgent.startTime;
      for (const sub of subagents.values()) {
        sub.duration = sub.endTime - sub.startTime;
      }

      // Calculate totals
      const subagentArray = Array.from(subagents.values());
      const totalInputTokens = mainAgent.inputTokens + subagentArray.reduce((sum, s) => sum + s.inputTokens, 0);
      const totalOutputTokens = mainAgent.outputTokens + subagentArray.reduce((sum, s) => sum + s.outputTokens, 0);
      const totalToolCalls = mainAgent.toolCalls + subagentArray.reduce((sum, s) => sum + s.toolCalls, 0);
      const totalLLMCalls = mainAgent.llmCalls + subagentArray.reduce((sum, s) => sum + s.llmCalls, 0);

      // Estimate cost for subagents based on token usage ratio
      // (since actual cost is only tracked at session level)
      const tokenRatioMain = mainAgent.inputTokens / Math.max(totalInputTokens, 1);
      const mainCost = mainAgent.estimatedCost;
      for (const sub of subagentArray) {
        const tokenRatio = sub.inputTokens / Math.max(totalInputTokens, 1);
        sub.estimatedCost = (mainCost / tokenRatioMain) * tokenRatio * (1 / Math.max(tokenRatioMain, 0.01));
      }

      const totalCost = mainAgent.estimatedCost + subagentArray.reduce((sum, s) => sum + s.estimatedCost, 0);

      return {
        sessionId: this.sessionId || 'unknown',
        mainAgent,
        subagents: subagentArray,
        totals: {
          inputTokens: totalInputTokens,
          outputTokens: totalOutputTokens,
          toolCalls: totalToolCalls,
          llmCalls: totalLLMCalls,
          estimatedCost: totalCost,
          duration: mainAgent.duration,
        },
      };
    } catch (error) {
      // File may not exist yet or be unreadable
      return null;
    }
  }
}

/**
 * Metrics data for a single agent (main or subagent).
 */
export interface AgentMetricsData {
  agentId: string;
  agentType: string;
  parentSessionId?: string;
  spawnedAtIteration?: number;
  inputTokens: number;
  outputTokens: number;
  toolCalls: number;
  llmCalls: number;
  estimatedCost: number;
  duration: number;
  startTime: number;
  endTime: number;
}

/**
 * Hierarchical view of all agents in a session.
 */
export interface SubagentHierarchy {
  sessionId: string;
  mainAgent: AgentMetricsData;
  subagents: AgentMetricsData[];
  totals: {
    inputTokens: number;
    outputTokens: number;
    toolCalls: number;
    llmCalls: number;
    estimatedCost: number;
    duration: number;
  };
}

// =============================================================================
// FACTORY FUNCTION
// =============================================================================

/**
 * Create a new trace collector.
 */
export function createTraceCollector(
  config: Partial<TraceCollectorConfig> = {}
): TraceCollector {
  return new TraceCollector(config);
}
