/**
 * Lesson 18: ReAct Loop
 *
 * Core implementation of the ReAct (Reasoning + Acting) pattern.
 * This creates an agent that explicitly reasons about each action
 * before taking it, producing a traceable thought chain.
 *
 * The loop follows: Thought → Action → Observation → Thought → ...
 */

import type {
  ReActStep,
  ReActTrace,
  ReActAction,
  ReActConfig,
  ReActError,
  ReActEvent,
  ReActEventListener,
  ReActToolRegistry,
  ParsedReActOutput,
  DEFAULT_REACT_CONFIG,
} from './types.js';
import { parseReActOutput } from './thought-parser.js';
import { formatObservation } from './observation-formatter.js';
import type { Message } from '../02-provider-abstraction/types.js';

// =============================================================================
// REACT AGENT
// =============================================================================

/**
 * ReAct agent that interleaves reasoning with action.
 *
 * Example usage:
 * ```ts
 * const agent = new ReActAgent(provider, tools, config);
 *
 * for await (const step of agent.run('Find all TypeScript files')) {
 *   console.log(`Thought: ${step.thought}`);
 *   console.log(`Action: ${step.action.tool}(${JSON.stringify(step.action.args)})`);
 *   console.log(`Observation: ${step.observation}`);
 * }
 * ```
 */
export class ReActAgent {
  private config: ReActConfig;
  private tools: ReActToolRegistry;
  private llm: LLMProvider;
  private listeners: Set<ReActEventListener> = new Set();

  constructor(
    llm: LLMProvider,
    tools: ReActToolRegistry,
    config: Partial<ReActConfig> = {}
  ) {
    this.llm = llm;
    this.tools = tools;
    this.config = {
      maxSteps: config.maxSteps ?? 10,
      stepTimeout: config.stepTimeout ?? 30000,
      includeObservations: config.includeObservations ?? true,
      maxObservationLength: config.maxObservationLength ?? 1000,
      verbose: config.verbose ?? false,
      promptConfig: {
        systemPrefix: config.promptConfig?.systemPrefix ?? '',
        formatInstructions: config.promptConfig?.formatInstructions ?? DEFAULT_FORMAT_INSTRUCTIONS,
        examples: config.promptConfig?.examples,
        stepSuffix: config.promptConfig?.stepSuffix ?? '',
      },
    };
  }

  // =============================================================================
  // MAIN EXECUTION
  // =============================================================================

  /**
   * Run the ReAct loop for a given goal.
   * Yields each step as it completes.
   */
  async *run(goal: string): AsyncGenerator<ReActStep, ReActTrace> {
    const startTime = performance.now();
    const steps: ReActStep[] = [];
    const errors: ReActError[] = [];

    this.emit({ type: 'start', goal });

    // Build initial messages
    const messages: Message[] = [
      { role: 'system', content: this.buildSystemPrompt() },
      { role: 'user', content: `Goal: ${goal}\n\nBegin!` },
    ];

    let stepNumber = 0;
    let finalAnswer: string | undefined;

    while (stepNumber < this.config.maxSteps) {
      stepNumber++;
      const stepStartTime = performance.now();

      try {
        // Get LLM response
        const response = await this.llmCall(messages);

        // Parse the response
        const parsed = parseReActOutput(response);

        if (!parsed.success) {
          const error: ReActError = {
            stepNumber,
            type: 'parse',
            message: `Failed to parse: ${parsed.errors.join(', ')}`,
            recoverable: true,
          };
          errors.push(error);
          this.emit({ type: 'error', error });

          // Add error feedback and retry
          messages.push(
            { role: 'assistant', content: response },
            { role: 'user', content: `Error: Could not parse your response. Please use the format:\nThought: [your reasoning]\nAction: tool_name({"arg": "value"})\n\nOr if you have the answer:\nFinal Answer: [your answer]` }
          );
          continue;
        }

        // Check for final answer
        if (parsed.isFinalAnswer && parsed.finalAnswer) {
          finalAnswer = parsed.finalAnswer;
          this.emit({ type: 'final_answer', answer: finalAnswer });
          break;
        }

        // Must have thought and action
        if (!parsed.thought || !parsed.action) {
          const error: ReActError = {
            stepNumber,
            type: 'parse',
            message: 'Missing thought or action',
            recoverable: true,
          };
          errors.push(error);
          this.emit({ type: 'error', error });
          continue;
        }

        this.emit({ type: 'thought', stepNumber, thought: parsed.thought });
        this.emit({ type: 'action', stepNumber, action: parsed.action });

        // Execute the action
        let observation: string;
        try {
          const result = await this.executeAction(parsed.action);
          observation = formatObservation(result, {
            maxLength: this.config.maxObservationLength,
            truncation: 'end',
            asCodeBlock: false,
            includeMetadata: false,
          }).content;
        } catch (err) {
          observation = `Error: ${err instanceof Error ? err.message : String(err)}`;
          errors.push({
            stepNumber,
            type: 'tool',
            message: observation,
            recoverable: true,
          });
        }

        this.emit({ type: 'observation', stepNumber, observation });

        // Create step
        const step: ReActStep = {
          stepNumber,
          thought: parsed.thought,
          action: parsed.action,
          observation,
          timestamp: new Date(),
          durationMs: performance.now() - stepStartTime,
        };

        steps.push(step);
        this.emit({ type: 'step_complete', step });

        // Update messages for next iteration
        messages.push(
          { role: 'assistant', content: response },
          { role: 'user', content: `Observation: ${observation}\n\nContinue with your next thought, or provide a Final Answer.` }
        );

        yield step;
      } catch (err) {
        const error: ReActError = {
          stepNumber,
          type: 'tool',
          message: err instanceof Error ? err.message : String(err),
          recoverable: false,
        };
        errors.push(error);
        this.emit({ type: 'error', error });
        break;
      }
    }

    // Check for max steps reached
    if (!finalAnswer && stepNumber >= this.config.maxSteps) {
      errors.push({
        stepNumber,
        type: 'max_steps',
        message: `Reached maximum steps (${this.config.maxSteps})`,
        recoverable: false,
      });
      finalAnswer = 'I was unable to complete the task within the step limit.';
    }

    // Build trace
    const trace: ReActTrace = {
      goal,
      steps,
      finalAnswer: finalAnswer ?? 'No answer provided',
      success: errors.filter((e) => !e.recoverable).length === 0 && !!finalAnswer,
      totalDurationMs: performance.now() - startTime,
      toolCallCount: steps.length,
      errors,
    };

    this.emit({ type: 'complete', trace });

    return trace;
  }

  /**
   * Run to completion and return the trace.
   */
  async runToCompletion(goal: string): Promise<ReActTrace> {
    const generator = this.run(goal);
    let result = await generator.next();

    while (!result.done) {
      result = await generator.next();
    }

    return result.value;
  }

  // =============================================================================
  // PROMPT BUILDING
  // =============================================================================

  /**
   * Build the system prompt for ReAct.
   */
  private buildSystemPrompt(): string {
    const parts: string[] = [];

    // Custom prefix
    if (this.config.promptConfig.systemPrefix) {
      parts.push(this.config.promptConfig.systemPrefix);
    }

    // Format instructions
    parts.push(this.config.promptConfig.formatInstructions);

    // Available tools
    parts.push('## Available Tools\n\n' + this.tools.getDescriptions());

    // Examples
    if (this.config.promptConfig.examples && this.config.promptConfig.examples.length > 0) {
      parts.push('## Examples\n\n' + this.formatExamples());
    }

    return parts.join('\n\n');
  }

  /**
   * Format few-shot examples.
   */
  private formatExamples(): string {
    const examples = this.config.promptConfig.examples ?? [];
    return examples.map((example, i) => {
      const steps = example.steps.map((s) =>
        `Thought: ${s.thought}\nAction: ${s.action}\nObservation: ${s.observation}`
      ).join('\n\n');

      return `### Example ${i + 1}\nGoal: ${example.goal}\n\n${steps}\n\nFinal Answer: ${example.finalAnswer}`;
    }).join('\n\n---\n\n');
  }

  // =============================================================================
  // ACTION EXECUTION
  // =============================================================================

  /**
   * Execute a ReAct action.
   */
  private async executeAction(action: ReActAction): Promise<string> {
    const tool = this.tools.get(action.tool);

    if (!tool) {
      throw new Error(`Unknown tool: ${action.tool}`);
    }

    const result = await this.tools.execute(action.tool, action.args);

    if (!result.success) {
      return `Tool execution failed: ${result.output}`;
    }

    return result.output;
  }

  /**
   * Make an LLM call with timeout.
   */
  private async llmCall(messages: Message[]): Promise<string> {
    // In a real implementation, this would call the actual LLM
    // For this educational example, we'll use a simple interface
    return this.llm.chat(messages);
  }

  // =============================================================================
  // EVENT HANDLING
  // =============================================================================

  /**
   * Subscribe to ReAct events.
   */
  on(listener: ReActEventListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /**
   * Emit an event.
   */
  private emit(event: ReActEvent): void {
    if (this.config.verbose) {
      console.log(`[ReAct] ${event.type}:`, event);
    }

    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch (err) {
        console.error('Error in ReAct listener:', err);
      }
    }
  }
}

// =============================================================================
// LLM PROVIDER INTERFACE
// =============================================================================

/**
 * Simple LLM provider interface for ReAct.
 */
export interface LLMProvider {
  chat(messages: Message[]): Promise<string>;
}

// =============================================================================
// DEFAULT PROMPTS
// =============================================================================

const DEFAULT_FORMAT_INSTRUCTIONS = `
You are a helpful assistant that solves problems step by step.

For each step, you should:
1. Think about what you need to do next
2. Take an action using one of the available tools
3. Observe the result
4. Continue until you have enough information to answer

Use this format:

Thought: [Your reasoning about what to do next]
Action: tool_name({"arg1": "value1", "arg2": "value2"})

After the action, you'll receive an observation. Continue the loop until you can provide:

Final Answer: [Your complete answer to the goal]

Important:
- Always think before acting
- Use tools to gather information, don't make assumptions
- If a tool fails, think about why and try a different approach
- Provide a Final Answer when you have enough information
`;

// =============================================================================
// EXPORTS
// =============================================================================

export { DEFAULT_FORMAT_INSTRUCTIONS };
