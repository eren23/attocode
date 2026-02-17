/**
 * Lesson 25: ReAct Pattern Integration
 *
 * Integrates the ReAct (Reasoning + Acting) pattern (from Lesson 18)
 * into the production agent. Enables explicit reasoning traces
 * with thought-action-observation loops.
 */

import type { LLMProvider, ToolDefinition, Message, ToolCall } from '../../types.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * ReAct configuration.
 */
export interface ReActConfig {
  /** Maximum reasoning steps */
  maxSteps: number;
  /** Stop on first valid answer */
  stopOnAnswer: boolean;
  /** Include reasoning in final output */
  includeReasoning: boolean;
  /** Custom patterns for parsing */
  patterns?: ReActPatterns;
}

/**
 * Patterns for parsing ReAct output.
 */
export interface ReActPatterns {
  thought: RegExp;
  action: RegExp;
  actionInput: RegExp;
  observation: RegExp;
  finalAnswer: RegExp;
}

/**
 * Single ReAct step.
 */
export interface ReActStep {
  stepNumber: number;
  thought: string;
  action?: ReActAction;
  observation?: string;
  isFinal: boolean;
}

/**
 * ReAct action (tool call).
 */
export interface ReActAction {
  tool: string;
  input: Record<string, unknown>;
}

/**
 * Full ReAct trace.
 */
export interface ReActTrace {
  steps: ReActStep[];
  finalAnswer?: string;
  success: boolean;
  totalSteps: number;
}

/**
 * ReAct events.
 */
export type ReActEvent =
  | { type: 'react.start'; task: string }
  | { type: 'react.thought'; step: number; thought: string }
  | { type: 'react.action'; step: number; action: ReActAction }
  | { type: 'react.observation'; step: number; observation: string }
  | { type: 'react.answer'; answer: string }
  | { type: 'react.complete'; trace: ReActTrace };

export type ReActEventListener = (event: ReActEvent) => void;

// =============================================================================
// DEFAULT PATTERNS
// =============================================================================

const DEFAULT_PATTERNS: ReActPatterns = {
  thought: /Thought:\s*(.+?)(?=Action:|Final Answer:|$)/is,
  action: /Action:\s*(\w+)/i,
  actionInput: /Action Input:\s*(.+?)(?=Thought:|Observation:|Final Answer:|$)/is,
  observation: /Observation:\s*(.+?)(?=Thought:|Action:|Final Answer:|$)/is,
  finalAnswer: /Final Answer:\s*(.+?)$/is,
};

const REACT_SYSTEM_PROMPT = `You are a helpful AI assistant that uses the ReAct (Reasoning + Acting) framework.

For each step:
1. Thought: Reason about what to do next
2. Action: Choose a tool to use
3. Action Input: Provide the input for the tool
4. Observation: (This will be provided after tool execution)

When you have enough information:
Final Answer: Provide your final response

Format your response exactly like this:
Thought: I need to...
Action: tool_name
Action Input: {"param": "value"}

Or when ready to answer:
Thought: I now have enough information...
Final Answer: The answer is...

Available tools:
{tools}`;

// =============================================================================
// REACT MANAGER
// =============================================================================

/**
 * ReActManager implements the ReAct reasoning pattern.
 */
export class ReActManager {
  private provider: LLMProvider;
  private tools: Map<string, ToolDefinition>;
  private config: ReActConfig;
  private patterns: ReActPatterns;
  private listeners: ReActEventListener[] = [];

  constructor(provider: LLMProvider, tools: ToolDefinition[], config: Partial<ReActConfig> = {}) {
    this.provider = provider;
    this.tools = new Map(tools.map((t) => [t.name, t]));
    this.config = {
      maxSteps: config.maxSteps ?? 15,
      stopOnAnswer: config.stopOnAnswer ?? true,
      includeReasoning: config.includeReasoning ?? true,
      patterns: config.patterns,
    };
    this.patterns = config.patterns ?? DEFAULT_PATTERNS;
  }

  /**
   * Run a task using the ReAct pattern.
   */
  async run(task: string): Promise<ReActTrace> {
    this.emit({ type: 'react.start', task });

    const trace: ReActTrace = {
      steps: [],
      success: false,
      totalSteps: 0,
    };

    const messages: Message[] = [
      { role: 'system', content: this.buildSystemPrompt() },
      { role: 'user', content: task },
    ];

    for (let step = 1; step <= this.config.maxSteps; step++) {
      // Get LLM response
      const response = await this.provider.chat(messages);
      const output = response.content;

      // Parse the response
      const parsed = this.parseOutput(output);

      const reactStep: ReActStep = {
        stepNumber: step,
        thought: parsed.thought || 'No explicit thought',
        isFinal: !!parsed.finalAnswer,
      };

      if (parsed.thought) {
        this.emit({ type: 'react.thought', step, thought: parsed.thought });
      }

      // Check for final answer
      if (parsed.finalAnswer) {
        trace.finalAnswer = parsed.finalAnswer;
        trace.success = true;
        reactStep.isFinal = true;
        trace.steps.push(reactStep);
        this.emit({ type: 'react.answer', answer: parsed.finalAnswer });
        break;
      }

      // Execute action if present
      if (parsed.action && parsed.actionInput) {
        const action: ReActAction = {
          tool: parsed.action,
          input: this.parseActionInput(parsed.actionInput),
        };
        reactStep.action = action;

        this.emit({ type: 'react.action', step, action });

        // Execute the tool
        const observation = await this.executeAction(action);
        reactStep.observation = observation;

        this.emit({ type: 'react.observation', step, observation });

        // Add to messages for next iteration
        messages.push(
          { role: 'assistant', content: output },
          { role: 'user', content: `Observation: ${observation}` },
        );
      } else {
        // No action, just add the response
        messages.push({ role: 'assistant', content: output });
      }

      trace.steps.push(reactStep);
      trace.totalSteps = step;
    }

    // If we exhausted steps without answer
    if (!trace.finalAnswer) {
      trace.success = false;
      trace.finalAnswer = 'Maximum steps reached without a final answer.';
    }

    this.emit({ type: 'react.complete', trace });

    return trace;
  }

  /**
   * Subscribe to events.
   */
  on(listener: ReActEventListener): () => void {
    this.listeners.push(listener);
    return () => {
      const idx = this.listeners.indexOf(listener);
      if (idx >= 0) this.listeners.splice(idx, 1);
    };
  }

  /**
   * Get the reasoning trace as a formatted string.
   */
  formatTrace(trace: ReActTrace): string {
    const lines: string[] = [];

    for (const step of trace.steps) {
      lines.push(`=== Step ${step.stepNumber} ===`);
      lines.push(`Thought: ${step.thought}`);

      if (step.action) {
        lines.push(`Action: ${step.action.tool}`);
        lines.push(`Input: ${JSON.stringify(step.action.input)}`);
      }

      if (step.observation) {
        lines.push(`Observation: ${step.observation}`);
      }

      if (step.isFinal) {
        lines.push(`[Final Step]`);
      }

      lines.push('');
    }

    if (trace.finalAnswer) {
      lines.push(`=== Final Answer ===`);
      lines.push(trace.finalAnswer);
    }

    return lines.join('\n');
  }

  // -------------------------------------------------------------------------
  // PRIVATE METHODS
  // -------------------------------------------------------------------------

  private emit(event: ReActEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch {
        // Ignore listener errors
      }
    }
  }

  private buildSystemPrompt(): string {
    const toolDescriptions = Array.from(this.tools.values())
      .map((t) => `- ${t.name}: ${t.description}`)
      .join('\n');

    return REACT_SYSTEM_PROMPT.replace('{tools}', toolDescriptions);
  }

  private parseOutput(output: string): {
    thought?: string;
    action?: string;
    actionInput?: string;
    finalAnswer?: string;
  } {
    const thoughtMatch = output.match(this.patterns.thought);
    const actionMatch = output.match(this.patterns.action);
    const actionInputMatch = output.match(this.patterns.actionInput);
    const finalAnswerMatch = output.match(this.patterns.finalAnswer);

    return {
      thought: thoughtMatch?.[1]?.trim(),
      action: actionMatch?.[1]?.trim(),
      actionInput: actionInputMatch?.[1]?.trim(),
      finalAnswer: finalAnswerMatch?.[1]?.trim(),
    };
  }

  private parseActionInput(input: string): Record<string, unknown> {
    try {
      return JSON.parse(input);
    } catch {
      // If not JSON, wrap as a single argument
      return { input };
    }
  }

  private async executeAction(action: ReActAction): Promise<string> {
    const tool = this.tools.get(action.tool);

    if (!tool) {
      return `Error: Unknown tool "${action.tool}". Available tools: ${Array.from(this.tools.keys()).join(', ')}`;
    }

    try {
      const result = await tool.execute(action.input);
      return this.formatObservation(result);
    } catch (error) {
      return `Error executing ${action.tool}: ${error instanceof Error ? error.message : 'Unknown error'}`;
    }
  }

  private formatObservation(result: unknown): string {
    if (typeof result === 'string') {
      return result;
    }

    if (result === null || result === undefined) {
      return 'No result';
    }

    try {
      return JSON.stringify(result, null, 2);
    } catch {
      return String(result);
    }
  }
}

// =============================================================================
// FACTORY
// =============================================================================

/**
 * Create a ReAct manager.
 */
export function createReActManager(
  provider: LLMProvider,
  tools: ToolDefinition[],
  config?: Partial<ReActConfig>,
): ReActManager {
  return new ReActManager(provider, tools, config);
}

// =============================================================================
// COMPARISON UTILITIES
// =============================================================================

/**
 * Compare ReAct trace with standard agent execution.
 */
export interface ReActComparison {
  reactTrace: ReActTrace;
  standardResult: string;
  reactSteps: number;
  reactHasExplicitReasoning: boolean;
  reasoningSteps: string[];
}

/**
 * Extract all thoughts from a trace.
 */
export function extractThoughts(trace: ReActTrace): string[] {
  return trace.steps.map((s) => s.thought).filter((t) => t && t !== 'No explicit thought');
}

/**
 * Extract all actions from a trace.
 */
export function extractActions(trace: ReActTrace): ReActAction[] {
  return trace.steps.filter((s) => s.action).map((s) => s.action!);
}

/**
 * Check if trace shows coherent reasoning.
 */
export function hasCoherentReasoning(trace: ReActTrace): boolean {
  const thoughts = extractThoughts(trace);

  // At least 2 thoughts for reasoning chain
  if (thoughts.length < 2) return false;

  // Check for progression keywords
  const progressionKeywords = ['then', 'next', 'now', 'based on', 'after', 'since'];
  const hasProgression = thoughts.some((t) =>
    progressionKeywords.some((k) => t.toLowerCase().includes(k)),
  );

  return hasProgression;
}
