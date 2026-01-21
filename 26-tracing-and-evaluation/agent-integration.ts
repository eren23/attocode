/**
 * Lesson 26: Agent Integration
 *
 * Provides trace collection integration for the ProductionAgent.
 * Hooks into the existing event system to capture comprehensive traces
 * without modifying the core agent code.
 *
 * @example
 * ```typescript
 * import { createProductionAgent } from '../25-production-agent/agent.js';
 * import { createTracedAgent, TracedAgentWrapper } from './agent-integration.js';
 *
 * // Option 1: Create traced agent directly
 * const tracedAgent = createTracedAgent({
 *   provider,
 *   tools,
 *   tracing: { outputDir: '.traces' }
 * });
 *
 * // Option 2: Wrap existing agent
 * const agent = createProductionAgent({ provider, tools });
 * const wrapper = new TracedAgentWrapper(agent);
 * wrapper.startTracing({ outputDir: '.traces' });
 *
 * const result = await tracedAgent.run('Write a function');
 * const trace = wrapper.getTrace();
 * ```
 */

import { randomUUID } from 'crypto';
import type { ProductionAgent } from '../25-production-agent/agent.js';
import { TraceCollector, createTraceCollector } from './trace-collector.js';
import type {
  TraceCollectorConfig,
  SessionTrace,
  TracedToolCall,
} from './types.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Configuration for traced agent.
 */
export interface TracingConfig extends Partial<TraceCollectorConfig> {
  /** Generate unique request IDs */
  generateRequestIds?: boolean;

  /** Capture detailed token breakdown */
  captureTokenBreakdown?: boolean;

  /** Log events to console */
  consoleLog?: boolean;
}

/**
 * Default tracing config.
 */
const DEFAULT_TRACING_CONFIG: TracingConfig = {
  enabled: true,
  generateRequestIds: true,
  captureTokenBreakdown: true,
  consoleLog: false,
  outputDir: '.traces',
  captureMessageContent: true,
  captureToolResults: true,
  maxResultSize: 10000,
  analyzeCacheBoundaries: true,
  filePattern: 'trace-{sessionId}-{timestamp}.jsonl',
};

/**
 * Event data from the production agent.
 */
interface AgentEventData {
  type: string;
  [key: string]: unknown;
}

// =============================================================================
// TRACED AGENT WRAPPER
// =============================================================================

/**
 * Wraps a ProductionAgent to add comprehensive tracing.
 */
export class TracedAgentWrapper {
  private agent: ProductionAgent;
  private collector: TraceCollector;
  private config: TracingConfig;
  private unsubscribe: (() => void) | null = null;

  // Request tracking
  private currentRequestId: string | null = null;
  private requestStartTime: number = 0;
  private currentMessages: Array<{
    role: 'system' | 'user' | 'assistant' | 'tool';
    content: string;
    toolCallId?: string;
  }> = [];
  private pendingToolCalls: Map<string, { name: string; args: Record<string, unknown>; startTime: number }> = new Map();
  private iterationNumber: number = 0;
  private sessionActive: boolean = false;

  constructor(agent: ProductionAgent, config: Partial<TracingConfig> = {}) {
    this.agent = agent;
    this.config = { ...DEFAULT_TRACING_CONFIG, ...config };
    this.collector = createTraceCollector(this.config);
  }

  /**
   * Start tracing for subsequent runs.
   */
  async startTracing(config?: Partial<TracingConfig>): Promise<void> {
    if (config) {
      this.config = { ...this.config, ...config };
      this.collector = createTraceCollector(this.config);
    }

    // Subscribe to agent events
    this.unsubscribe = this.agent.subscribe((event: AgentEventData) => {
      this.handleAgentEvent(event);
    });
  }

  /**
   * Stop tracing.
   */
  stopTracing(): void {
    if (this.unsubscribe) {
      this.unsubscribe();
      this.unsubscribe = null;
    }
  }

  /**
   * Run a task with tracing enabled.
   */
  async runTraced(task: string): Promise<{ result: Awaited<ReturnType<ProductionAgent['run']>>; trace: SessionTrace }> {
    const sessionId = randomUUID();
    const model = (this.agent as unknown as { config: { model: string } }).config?.model ?? 'unknown';

    // Start session
    await this.collector.startSession(sessionId, task, model);
    this.sessionActive = true;
    this.iterationNumber = 0;

    // Subscribe to events if not already
    if (!this.unsubscribe) {
      await this.startTracing();
    }

    try {
      // Run the agent
      const result = await this.agent.run(task);

      // End session
      const trace = await this.collector.endSession({
        success: result.success,
        output: result.response,
        failureReason: result.error,
      });

      this.sessionActive = false;
      return { result, trace };
    } catch (err) {
      // End session with failure
      const error = err instanceof Error ? err : new Error(String(err));
      const trace = await this.collector.endSession({
        success: false,
        failureReason: error.message,
      });

      this.sessionActive = false;
      throw err;
    }
  }

  /**
   * Get the underlying collector.
   */
  getCollector(): TraceCollector {
    return this.collector;
  }

  /**
   * Get the last trace (if session completed).
   */
  getLastTrace(): SessionTrace | null {
    // The trace is returned by endSession, not stored in collector
    // This is a placeholder for future implementation
    return null;
  }

  // ===========================================================================
  // EVENT HANDLING
  // ===========================================================================

  /**
   * Handle agent events and convert to trace events.
   */
  private handleAgentEvent(event: AgentEventData): void {
    if (!this.sessionActive) return;

    if (this.config.consoleLog) {
      console.log(`[Trace] ${event.type}`, JSON.stringify(event).slice(0, 200));
    }

    switch (event.type) {
      case 'llm.start':
        this.handleLLMStart(event);
        break;

      case 'llm.complete':
        this.handleLLMComplete(event);
        break;

      case 'tool.start':
        this.handleToolStart(event);
        break;

      case 'tool.complete':
        this.handleToolComplete(event);
        break;

      case 'tool.blocked':
        this.handleToolBlocked(event);
        break;

      case 'error':
        this.handleError(event);
        break;
    }
  }

  /**
   * Handle LLM request start.
   */
  private handleLLMStart(event: AgentEventData): void {
    // Start new iteration
    this.iterationNumber++;
    this.collector.record({
      type: 'iteration.start',
      data: { iterationNumber: this.iterationNumber },
    });

    // Generate request ID
    this.currentRequestId = this.config.generateRequestIds
      ? `req-${this.iterationNumber}-${Date.now()}`
      : `req-${this.iterationNumber}`;
    this.requestStartTime = Date.now();

    // Get current messages from agent state
    const agentState = this.agent.getState();
    this.currentMessages = agentState.messages.map(m => ({
      role: m.role as 'system' | 'user' | 'assistant' | 'tool',
      content: m.content,
      toolCallId: m.toolCallId,
    }));

    // Record LLM request
    const model = (event.model as string) ?? 'unknown';
    this.collector.record({
      type: 'llm.request',
      data: {
        requestId: this.currentRequestId,
        model,
        provider: 'anthropic', // Default assumption
        messages: this.currentMessages,
        tools: this.getToolDefinitions(),
        parameters: {
          maxTokens: 4096,
        },
      },
    });
  }

  /**
   * Handle LLM response complete.
   */
  private handleLLMComplete(event: AgentEventData): void {
    if (!this.currentRequestId) return;

    const response = event.response as {
      content?: string;
      toolCalls?: TracedToolCall[];
      usage?: {
        inputTokens?: number;
        outputTokens?: number;
        cacheReadTokens?: number;
        cacheWriteTokens?: number;
      };
    } | undefined;

    const durationMs = Date.now() - this.requestStartTime;

    // Determine stop reason
    const hasToolCalls = response?.toolCalls && response.toolCalls.length > 0;
    const stopReason = hasToolCalls ? 'tool_use' : 'end_turn';

    // Record LLM response
    this.collector.record({
      type: 'llm.response',
      data: {
        requestId: this.currentRequestId,
        content: response?.content ?? '',
        toolCalls: response?.toolCalls,
        stopReason,
        usage: {
          inputTokens: response?.usage?.inputTokens ?? 0,
          outputTokens: response?.usage?.outputTokens ?? 0,
          cacheReadTokens: response?.usage?.cacheReadTokens,
          cacheWriteTokens: response?.usage?.cacheWriteTokens,
        },
        durationMs,
      },
    });

    // End iteration if no tool calls
    if (!hasToolCalls) {
      this.collector.record({
        type: 'iteration.end',
        data: { iterationNumber: this.iterationNumber },
      });
    }

    this.currentRequestId = null;
  }

  /**
   * Handle tool execution start.
   */
  private handleToolStart(event: AgentEventData): void {
    const toolName = event.tool as string;
    const args = (event.args as Record<string, unknown>) ?? {};
    const executionId = `exec-${this.iterationNumber}-${toolName}-${Date.now()}`;

    this.pendingToolCalls.set(toolName, {
      name: toolName,
      args,
      startTime: Date.now(),
    });

    this.collector.record({
      type: 'tool.start',
      data: {
        executionId,
        toolName,
        arguments: args,
      },
    });
  }

  /**
   * Handle tool execution complete.
   */
  private handleToolComplete(event: AgentEventData): void {
    const toolName = event.tool as string;
    const pending = this.pendingToolCalls.get(toolName);

    if (!pending) return;

    const durationMs = Date.now() - pending.startTime;
    const executionId = `exec-${this.iterationNumber}-${toolName}-${pending.startTime}`;

    this.collector.record({
      type: 'tool.end',
      data: {
        executionId,
        status: 'success',
        result: event.result,
        durationMs,
      },
    });

    this.pendingToolCalls.delete(toolName);

    // End iteration after all tools complete
    if (this.pendingToolCalls.size === 0) {
      this.collector.record({
        type: 'iteration.end',
        data: { iterationNumber: this.iterationNumber },
      });
    }
  }

  /**
   * Handle tool blocked/error.
   */
  private handleToolBlocked(event: AgentEventData): void {
    const toolName = event.tool as string;
    const reason = event.reason as string;
    const pending = this.pendingToolCalls.get(toolName);

    if (!pending) return;

    const durationMs = Date.now() - pending.startTime;
    const executionId = `exec-${this.iterationNumber}-${toolName}-${pending.startTime}`;

    this.collector.record({
      type: 'tool.end',
      data: {
        executionId,
        status: 'blocked',
        error: new Error(reason),
        durationMs,
      },
    });

    this.pendingToolCalls.delete(toolName);
  }

  /**
   * Handle error event.
   */
  private handleError(event: AgentEventData): void {
    const errorMessage = event.error as string;

    this.collector.record({
      type: 'error',
      data: {
        code: 'AGENT_ERROR',
        message: errorMessage,
        context: `iteration ${this.iterationNumber}`,
        recoverable: true,
      },
    });
  }

  /**
   * Get tool definitions from agent.
   */
  private getToolDefinitions(): Array<{
    name: string;
    description: string;
    parametersSchema: Record<string, unknown>;
  }> {
    const tools = this.agent.getTools();
    return tools.map(t => ({
      name: t.name,
      description: t.description,
      parametersSchema: t.parameters ?? {},
    }));
  }
}

// =============================================================================
// FACTORY FUNCTIONS
// =============================================================================

/**
 * Create a traced agent wrapper.
 */
export function createTracedAgentWrapper(
  agent: ProductionAgent,
  config?: Partial<TracingConfig>
): TracedAgentWrapper {
  return new TracedAgentWrapper(agent, config);
}

/**
 * Run a task with tracing and return both result and trace.
 */
export async function runWithTracing(
  agent: ProductionAgent,
  task: string,
  config?: Partial<TracingConfig>
): Promise<{ result: Awaited<ReturnType<ProductionAgent['run']>>; trace: SessionTrace }> {
  const wrapper = new TracedAgentWrapper(agent, config);
  await wrapper.startTracing();

  try {
    return await wrapper.runTraced(task);
  } finally {
    wrapper.stopTracing();
  }
}
