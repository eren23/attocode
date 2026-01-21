/**
 * Lesson 9: Complete Agent Loop
 *
 * The main agent loop that ties everything together:
 * - Native tool use (no JSON parsing from text)
 * - Permission system integration
 * - Event-driven architecture for real-time feedback
 * - State tracking to prevent "forgetting"
 * - Context management for persistent conversations
 * - Cache-aware token tracking
 */

import type {
  CompleteAgentConfig,
  AgentEvent,
  AgentResult,
  ConversationMessage,
  ConversationState,
  LLMProviderWithTools,
  MessageWithContent,
} from './types.js';
import { ToolRegistry } from '../03-tool-system/registry.js';
import { toOpenRouterSchemas } from './tools.js';
import type { ContextManager } from './context/context-manager.js';

// =============================================================================
// SYSTEM PROMPT
// =============================================================================

/**
 * ═══════════════════════════════════════════════════════════════════════════
 * System Prompt Design: Why This Structure Matters
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * A well-structured system prompt prevents common agent mistakes:
 *
 * 1. CLEAR BOUNDARIES: "Use tools - never simulate results"
 *    Without this, LLMs often "imagine" what a file contains
 *
 * 2. ONE TOOL AT A TIME: Prevents complex multi-tool plans that fail
 *    Better to make progress incrementally than plan big and fail
 *
 * 3. EXPLICIT COMPLETION: Clear signal for when task is done
 *    Without this, agents often loop forever or stop randomly
 *
 * 4. STATE AWARENESS: Tool descriptions help LLM remember what's available
 *    Dynamic tool list prevents hallucinating non-existent tools
 * ═══════════════════════════════════════════════════════════════════════════
 */

function buildSystemPrompt(registry: ToolRegistry): string {
  const toolList = registry.getDescriptions()
    .map(t => `  • ${t.name}: ${t.description}`)
    .join('\n');

  // System prompt needs to be 1024+ tokens for caching to work with Anthropic models
  return `You are a helpful coding assistant with access to tools for file operations and command execution.

## Available Tools
${toolList}

## Tool Usage Rules
1. ALWAYS use tools to interact with the file system - never simulate or imagine results
2. Use ONE tool per response - wait for the result before deciding the next action
3. If a tool fails, analyze the error and try a different approach
4. Read files before modifying them to understand their current state

## Response Format
- To use a tool: The system will detect tool calls automatically
- To complete the task: Respond with a summary of what was accomplished
- If you cannot complete the task: Explain what went wrong and what was tried

## Important
- Be concise in your responses
- When reading files, summarize relevant parts rather than quoting everything
- For edits, use edit_file with precise old_string matching (include enough context for uniqueness)

## Code Quality Standards

When writing or modifying code, follow these best practices:

### General Principles
- Write clean, readable code with meaningful variable and function names
- Follow the existing code style and conventions in the project
- Keep functions small and focused on a single responsibility
- Add comments only when the code isn't self-explanatory
- Prefer explicit over implicit behavior

### Error Handling
- Always handle potential errors gracefully
- Provide meaningful error messages that help diagnose issues
- Don't swallow errors silently - log or report them appropriately
- Consider edge cases and invalid inputs

### Testing Considerations
- Write code that is testable and modular
- Consider how the code will be tested when designing interfaces
- Avoid tight coupling between components
- Make dependencies explicit and injectable

### Security Awareness
- Never hardcode sensitive information (API keys, passwords, etc.)
- Validate and sanitize user inputs
- Be cautious with file system operations
- Follow the principle of least privilege

### Performance
- Be mindful of performance implications in loops and data processing
- Avoid premature optimization but don't ignore obvious inefficiencies
- Consider memory usage with large data structures
- Use appropriate data structures for the task

### Documentation
- Document public APIs and complex logic
- Include examples in documentation when helpful
- Keep documentation up to date with code changes
- Explain the "why" not just the "what"

## File Operation Guidelines

### Reading Files
- Always check if a file exists before attempting operations
- Handle encoding properly (UTF-8 by default)
- For large files, consider reading in chunks if needed
- Summarize file contents rather than repeating everything verbatim

### Writing Files
- Create backup or use safe write patterns for critical files
- Verify write operations completed successfully
- Maintain consistent line endings
- Respect file permissions

### Editing Files
- Use precise string matching with enough context for uniqueness
- Verify the old_string exists exactly as specified before editing
- Test edits carefully before committing changes
- Make atomic changes when possible

## Command Execution Guidelines

### Shell Commands
- Prefer simple, well-known commands
- Quote arguments properly to handle spaces and special characters
- Set appropriate timeouts for long-running commands
- Capture both stdout and stderr for debugging

### Safety
- Never execute commands that could be destructive without confirmation
- Be especially careful with rm, chmod, chown, and similar commands
- Validate command outputs before using them in subsequent operations
- Consider the working directory context

## Conversation Guidelines

### Context Awareness
- Remember what files have been read and modified in this session
- Track the overall goal and current progress
- Reference previous findings when relevant
- Maintain consistency across multiple interactions

### Communication Style
- Be direct and concise in responses
- Explain your reasoning when making decisions
- Ask clarifying questions when requirements are ambiguous
- Provide actionable suggestions and next steps

### Progress Tracking
- Summarize completed steps and remaining work
- Highlight any blockers or issues encountered
- Suggest alternative approaches when stuck
- Celebrate successful completion of tasks

This comprehensive guide ensures consistent, high-quality assistance across all coding tasks.`;
}

// =============================================================================
// AGENT LOOP
// =============================================================================

/**
 * Run the complete agent loop.
 *
 * This is the core agent implementation that:
 * 1. Sends the task to the LLM with tool definitions
 * 2. Handles tool calls using native tool use (not JSON parsing)
 * 3. Feeds results back to the LLM
 * 4. Continues until task complete or max iterations
 *
 * @param task - The user's request
 * @param registry - Tool registry with permissions configured
 * @param config - Agent configuration
 * @returns Result with success status, message, and statistics
 */
export async function runAgent(
  task: string,
  registry: ToolRegistry,
  config: CompleteAgentConfig
): Promise<AgentResult> {
  const emit = (event: AgentEvent) => config.onEvent?.(event);

  // Initialize conversation with system prompt and user task
  const messages: ConversationMessage[] = [
    { role: 'system', content: buildSystemPrompt(registry) },
    { role: 'user', content: task },
  ];

  // Get tool schemas for OpenRouter
  const toolSchemas = toOpenRouterSchemas(registry.getDescriptions());

  // Track statistics
  let iterations = 0;
  let totalInputTokens = 0;
  let totalOutputTokens = 0;
  let totalCachedTokens = 0;
  const toolCallHistory: AgentResult['toolCalls'] = [];

  // State tracking (helps prevent agent from forgetting what it did)
  const state: ConversationState = {
    filesRead: new Set(),
    filesModified: new Set(),
    commandsExecuted: [],
    currentTask: task,
  };

  emit({ type: 'thinking', message: 'Starting task...' });

  // Main agent loop
  while (iterations < config.maxIterations) {
    iterations++;
    emit({ type: 'iteration', current: iterations, max: config.maxIterations });

    try {
      // Call LLM with native tool use (with retry for transient errors)
      const response = await retryWithBackoff(async () => {
        return config.provider.chatWithTools(messages, {
          tools: toolSchemas,
          tool_choice: 'auto',
          model: config.model,
          maxTokens: 4096,
        });
      }, {
        maxRetries: 3,
        initialDelayMs: 1000,
        onRetry: (attempt, error) => {
          emit({ type: 'thinking', message: `Retrying (attempt ${attempt + 1}/3): ${error.message}` });
        },
      });

      // Track token usage (including cached tokens)
      if (response.usage) {
        totalInputTokens += response.usage.inputTokens;
        totalOutputTokens += response.usage.outputTokens;
        totalCachedTokens += response.usage.cachedTokens ?? 0;

        // Emit cache hit event if tokens were cached
        if (response.usage.cachedTokens && response.usage.cachedTokens > 0) {
          emit({
            type: 'cache_hit',
            tokens: response.usage.cachedTokens,
          });
        }
      }

      // Check for tool calls
      if (response.toolCalls && response.toolCalls.length > 0) {
        // Process each tool call
        for (const toolCall of response.toolCalls) {
          // Parse args safely (handles malformed JSON from LLM)
          const args = safeParseToolArgs(toolCall.function.arguments, toolCall.function.name);

          emit({
            type: 'tool_call',
            name: toolCall.function.name,
            args,
          });
          const result = await registry.execute(toolCall.function.name, args);

          emit({
            type: 'tool_result',
            name: toolCall.function.name,
            result,
          });

          // Track state
          updateState(state, toolCall.function.name, args);

          // Record for history
          toolCallHistory.push({
            name: toolCall.function.name,
            args,
            result,
          });

          // Add assistant message with tool call
          messages.push({
            role: 'assistant',
            content: response.content || '',
            tool_calls: [toolCall],
          } as MessageWithContent);

          // Add tool result message (include name for Gemini compatibility)
          messages.push({
            role: 'tool',
            content: formatToolResult(result),
            tool_call_id: toolCall.id,
            name: toolCall.function.name,
          } as MessageWithContent);
        }
      } else {
        // No tool calls - task is complete (or LLM gave up)
        emit({ type: 'response', content: response.content });

        const result: AgentResult = {
          success: true,
          message: response.content,
          iterations,
          usage: {
            inputTokens: totalInputTokens,
            outputTokens: totalOutputTokens,
            cachedTokens: totalCachedTokens,
          },
          toolCalls: toolCallHistory,
          history: messages,
        };

        emit({ type: 'complete', result });
        return result;
      }
    } catch (error) {
      const err = error as Error;
      emit({ type: 'error', error: err });

      // Return failure result
      return {
        success: false,
        message: `Agent error: ${err.message}`,
        iterations,
        usage: {
          inputTokens: totalInputTokens,
          outputTokens: totalOutputTokens,
          cachedTokens: totalCachedTokens,
        },
        toolCalls: toolCallHistory,
        history: messages,
      };
    }
  }

  // Max iterations reached
  emit({ type: 'error', error: new Error('Max iterations reached') });

  return {
    success: false,
    message: `Task incomplete: reached maximum iterations (${config.maxIterations}). Last progress: ${summarizeState(state)}`,
    iterations,
    usage: {
      inputTokens: totalInputTokens,
      outputTokens: totalOutputTokens,
      cachedTokens: totalCachedTokens,
    },
    toolCalls: toolCallHistory,
    history: messages,
  };
}

// =============================================================================
// CONTEXT-AWARE AGENT
// =============================================================================

/**
 * Run agent with persistent context.
 *
 * Unlike runAgent which starts fresh each time, this version:
 * 1. Uses existing conversation history from ContextManager
 * 2. Appends new messages to the context
 * 3. Tracks state across multiple tasks
 *
 * @param task - The user's request
 * @param registry - Tool registry
 * @param config - Agent configuration
 * @param contextManager - Context manager with existing conversation
 * @returns Result with history persisted to context manager
 */
export async function runAgentWithContext(
  task: string,
  registry: ToolRegistry,
  config: CompleteAgentConfig,
  contextManager: ContextManager
): Promise<AgentResult> {
  const emit = (event: AgentEvent) => config.onEvent?.(event);

  // Check if this is the first message (need to add system prompt)
  if (contextManager.getMessageCount() === 0) {
    contextManager.addSystemMessage(buildSystemPrompt(registry));
  }

  // Add user task to context
  contextManager.addUserMessage(task);
  contextManager.setCurrentTask(task);

  // Get all messages from context for API call
  const messages = contextManager.getMessages() as ConversationMessage[];

  // Get tool schemas
  const toolSchemas = toOpenRouterSchemas(registry.getDescriptions());

  // Track statistics
  let iterations = 0;
  let totalInputTokens = 0;
  let totalOutputTokens = 0;
  let totalCachedTokens = 0;
  const toolCallHistory: AgentResult['toolCalls'] = [];

  emit({ type: 'thinking', message: 'Starting task...' });

  // Main agent loop
  while (iterations < config.maxIterations) {
    iterations++;
    emit({ type: 'iteration', current: iterations, max: config.maxIterations });

    try {
      const response = await config.provider.chatWithTools(messages, {
        tools: toolSchemas,
        tool_choice: 'auto',
        model: config.model,
        maxTokens: 4096,
      });

      // Track token usage
      if (response.usage) {
        totalInputTokens += response.usage.inputTokens;
        totalOutputTokens += response.usage.outputTokens;
        totalCachedTokens += response.usage.cachedTokens ?? 0;

        if (response.usage.cachedTokens && response.usage.cachedTokens > 0) {
          emit({ type: 'cache_hit', tokens: response.usage.cachedTokens });
        }
      }

      // Check for tool calls
      if (response.toolCalls && response.toolCalls.length > 0) {
        for (const toolCall of response.toolCalls) {
          // Parse args safely (handles malformed JSON from LLM)
          const args = safeParseToolArgs(toolCall.function.arguments, toolCall.function.name);

          emit({
            type: 'tool_call',
            name: toolCall.function.name,
            args,
          });

          const result = await registry.execute(toolCall.function.name, args);

          emit({
            type: 'tool_result',
            name: toolCall.function.name,
            result,
          });

          // Track state in context manager
          trackToolInContext(contextManager, toolCall.function.name, args);

          toolCallHistory.push({ name: toolCall.function.name, args, result });

          // Add to messages array for next iteration
          const assistantMsg = {
            role: 'assistant' as const,
            content: response.content || '',
            tool_calls: [toolCall],
          };
          messages.push(assistantMsg as ConversationMessage);
          contextManager.addMessage(assistantMsg);

          const toolMsg = {
            role: 'tool' as const,
            content: formatToolResult(result),
            tool_call_id: toolCall.id,
            name: toolCall.function.name, // Required for Gemini
          };
          messages.push(toolMsg as ConversationMessage);
          contextManager.addMessage(toolMsg);
        }
      } else {
        // Task complete - add response to context
        contextManager.addAssistantMessage(response.content);
        emit({ type: 'response', content: response.content });

        const result: AgentResult = {
          success: true,
          message: response.content,
          iterations,
          usage: {
            inputTokens: totalInputTokens,
            outputTokens: totalOutputTokens,
            cachedTokens: totalCachedTokens,
          },
          toolCalls: toolCallHistory,
          history: messages,
        };

        emit({ type: 'complete', result });
        return result;
      }
    } catch (error) {
      const err = error as Error;
      emit({ type: 'error', error: err });

      return {
        success: false,
        message: `Agent error: ${err.message}`,
        iterations,
        usage: {
          inputTokens: totalInputTokens,
          outputTokens: totalOutputTokens,
          cachedTokens: totalCachedTokens,
        },
        toolCalls: toolCallHistory,
        history: messages,
      };
    }
  }

  emit({ type: 'error', error: new Error('Max iterations reached') });

  return {
    success: false,
    message: `Task incomplete: reached maximum iterations (${config.maxIterations})`,
    iterations,
    usage: {
      inputTokens: totalInputTokens,
      outputTokens: totalOutputTokens,
      cachedTokens: totalCachedTokens,
    },
    toolCalls: toolCallHistory,
    history: messages,
  };
}

/**
 * Track tool execution in context manager.
 */
function trackToolInContext(
  contextManager: ContextManager,
  toolName: string,
  args: Record<string, unknown>
): void {
  switch (toolName) {
    case 'read_file':
      if (args.path) contextManager.trackFileRead(args.path as string);
      break;
    case 'write_file':
    case 'edit_file':
      if (args.path) contextManager.trackFileModified(args.path as string);
      break;
    case 'bash':
      if (args.command) contextManager.trackCommand(args.command as string);
      break;
  }
}

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

/**
 * Format tool result for the LLM.
 * Clear formatting helps the LLM understand what happened.
 * Truncates very long outputs to prevent token limits.
 */
const MAX_TOOL_OUTPUT_LENGTH = 50000; // ~12k tokens max per tool output

/**
 * Retry a function with exponential backoff for transient errors.
 */
interface RetryOptions {
  maxRetries: number;
  initialDelayMs: number;
  onRetry?: (attempt: number, error: Error) => void;
}

async function retryWithBackoff<T>(
  fn: () => Promise<T>,
  options: RetryOptions
): Promise<T> {
  const { maxRetries, initialDelayMs, onRetry } = options;

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await fn();
    } catch (error) {
      const err = error as Error;

      // Check if this is a retryable error
      const isRetryable =
        err.message.includes('fetch failed') ||
        err.message.includes('timeout') ||
        err.message.includes('ECONNRESET') ||
        err.message.includes('ETIMEDOUT') ||
        err.message.includes('rate limit') ||
        err.message.includes('503') ||
        err.message.includes('502') ||
        err.message.includes('429');

      if (!isRetryable || attempt === maxRetries) {
        throw error;
      }

      // Notify about retry
      if (onRetry) {
        onRetry(attempt, err);
      }

      // Exponential backoff with jitter
      const delay = initialDelayMs * Math.pow(2, attempt) + Math.random() * 1000;
      await new Promise((resolve) => setTimeout(resolve, delay));
    }
  }

  throw new Error('Retry exhausted'); // Should never reach here
}

function formatToolResult(result: { success: boolean; output: string }): string {
  const status = result.success ? '✓ Success' : '✗ Failed';
  let output = result.output;

  // Truncate very long outputs
  if (output.length > MAX_TOOL_OUTPUT_LENGTH) {
    const truncated = output.slice(0, MAX_TOOL_OUTPUT_LENGTH);
    const remaining = output.length - MAX_TOOL_OUTPUT_LENGTH;
    output = `${truncated}\n\n... [Output truncated: ${remaining.toLocaleString()} more characters. Use more specific queries to see full content.]`;
  }

  return `${status}\n\n${output}`;
}

/**
 * Safely parse JSON from LLM tool call arguments.
 * Attempts to fix common LLM JSON mistakes.
 */
function safeParseToolArgs(argsString: string, toolName: string): Record<string, unknown> {
  // Try direct parse first
  try {
    return JSON.parse(argsString);
  } catch (firstError) {
    // Try common fixes
    let fixed = argsString;

    // Fix 1: Remove trailing commas before } or ]
    fixed = fixed.replace(/,(\s*[}\]])/g, '$1');

    // Fix 2: Fix unquoted keys (simple cases)
    fixed = fixed.replace(/(\{|\,)\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:/g, '$1"$2":');

    // Fix 3: Fix single quotes to double quotes
    fixed = fixed.replace(/'/g, '"');

    // Fix 4: Remove control characters
    fixed = fixed.replace(/[\x00-\x1F\x7F]/g, '');

    // Fix 5: Try to extract JSON object if there's extra text
    const jsonMatch = fixed.match(/\{[\s\S]*\}/);
    if (jsonMatch) {
      fixed = jsonMatch[0];
    }

    try {
      return JSON.parse(fixed);
    } catch (secondError) {
      // If still failing, try to create a minimal valid args object
      // by extracting key-value pairs with regex
      const pairs: Record<string, unknown> = {};
      const kvRegex = /"?([a-zA-Z_][a-zA-Z0-9_]*)"?\s*:\s*("([^"]*)"|(true|false|null|\d+\.?\d*))/g;
      let match;

      while ((match = kvRegex.exec(argsString)) !== null) {
        const key = match[1];
        const value = match[3] !== undefined ? match[3] :
                     match[4] === 'true' ? true :
                     match[4] === 'false' ? false :
                     match[4] === 'null' ? null :
                     !isNaN(Number(match[4])) ? Number(match[4]) : match[4];
        pairs[key] = value;
      }

      if (Object.keys(pairs).length > 0) {
        console.warn(`[Agent] Recovered partial args for ${toolName}:`, pairs);
        return pairs;
      }

      // Give up - throw with helpful message
      throw new Error(
        `Invalid JSON in tool call "${toolName}". ` +
        `Original error: ${(firstError as Error).message}. ` +
        `Args received: ${argsString.slice(0, 200)}${argsString.length > 200 ? '...' : ''}`
      );
    }
  }
}

/**
 * Update state tracking based on tool execution.
 */
function updateState(
  state: ConversationState,
  toolName: string,
  args: Record<string, unknown>
): void {
  switch (toolName) {
    case 'read_file':
      if (args.path) state.filesRead.add(args.path as string);
      break;
    case 'write_file':
    case 'edit_file':
      if (args.path) state.filesModified.add(args.path as string);
      break;
    case 'bash':
      if (args.command) state.commandsExecuted.push(args.command as string);
      break;
  }
}

/**
 * Summarize what the agent has done (for max iteration message).
 */
function summarizeState(state: ConversationState): string {
  const parts: string[] = [];

  if (state.filesRead.size > 0) {
    parts.push(`Read ${state.filesRead.size} file(s)`);
  }
  if (state.filesModified.size > 0) {
    parts.push(`Modified ${state.filesModified.size} file(s)`);
  }
  if (state.commandsExecuted.length > 0) {
    parts.push(`Ran ${state.commandsExecuted.length} command(s)`);
  }

  return parts.length > 0 ? parts.join(', ') : 'No actions completed';
}

// =============================================================================
// CONVENIENCE FACTORY
// =============================================================================

/**
 * Create a configured agent runner.
 *
 * @example
 * ```typescript
 * const agent = createAgent(provider, registry, { maxIterations: 10 });
 * const result = await agent.run('Create a hello world TypeScript file');
 * ```
 */
export function createAgent(
  provider: LLMProviderWithTools,
  registry: ToolRegistry,
  options: Partial<Omit<CompleteAgentConfig, 'provider'>> = {}
): {
  run: (task: string) => Promise<AgentResult>;
  config: CompleteAgentConfig;
} {
  const config: CompleteAgentConfig = {
    provider,
    maxIterations: options.maxIterations ?? 20,
    enableCaching: options.enableCaching ?? false,
    permissionMode: options.permissionMode ?? 'interactive',
    onEvent: options.onEvent,
    model: options.model,
  };

  return {
    run: (task: string) => runAgent(task, registry, config),
    config,
  };
}
