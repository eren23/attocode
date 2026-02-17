/**
 * Mock Provider
 *
 * A mock LLM provider for testing and demonstration.
 * Always available as a fallback.
 */

import type {
  LLMProvider,
  LLMProviderWithTools,
  Message,
  MessageWithContent,
  ChatOptions,
  ChatOptionsWithTools,
  ChatResponse,
  ChatResponseWithTools,
  ToolCallResponse,
} from '../types.js';
import { registerProvider } from '../provider.js';
import { estimateTokenCount } from '../../integrations/utilities/token-estimate.js';

// =============================================================================
// MOCK RESPONSE PATTERNS
// =============================================================================

interface MockScenario {
  trigger: RegExp;
  responses: string[];
}

const SCENARIOS: MockScenario[] = [
  {
    trigger: /hello\s*world|create.*file/i,
    responses: [
      `I'll create a hello world file for you.

\`\`\`json
{ "tool": "write_file", "input": { "path": "hello.ts", "content": "console.log('Hello, World!');" } }
\`\`\``,
      "I've created hello.ts with a simple Hello World program. You can run it with `npx tsx hello.ts`.",
    ],
  },
  {
    trigger: /list|show.*files|what.*files/i,
    responses: [
      `I'll list the files in the current directory.

\`\`\`json
{ "tool": "list_files", "input": { "path": "." } }
\`\`\``,
      'Here are the files I found in the directory.',
    ],
  },
  {
    trigger: /read|show.*content|what.*in/i,
    responses: [
      `I'll read that file for you.

\`\`\`json
{ "tool": "read_file", "input": { "path": "package.json" } }
\`\`\``,
      'Here are the contents of the file.',
    ],
  },
  {
    trigger: /fix|debug|error/i,
    responses: [
      `Let me analyze the issue. First, I'll read the file.

\`\`\`json
{ "tool": "read_file", "input": { "path": "src/main.ts" } }
\`\`\``,
      `I see the issue. Let me fix it.

\`\`\`json
{ "tool": "edit_file", "input": { "path": "src/main.ts", "old": "bug", "new": "fix" } }
\`\`\``,
      "I've fixed the bug. The issue was caused by incorrect variable scope.",
    ],
  },
];

// =============================================================================
// MOCK PROVIDER
// =============================================================================

export class MockProvider implements LLMProvider, LLMProviderWithTools {
  readonly name = 'mock';
  readonly defaultModel = 'mock-model';

  private callCount = 0;
  private currentScenario: MockScenario | null = null;
  private scenarioIndex = 0;
  private toolResponses: Array<{ content: string; toolCalls?: ToolCallResponse[] }> = [];
  private toolResponseIndex = 0;

  isConfigured(): boolean {
    return true; // Always available
  }

  async chat(
    messages: (Message | MessageWithContent)[],
    _options?: ChatOptions,
  ): Promise<ChatResponse> {
    // Simulate network latency
    await new Promise((resolve) => setTimeout(resolve, 100));

    this.callCount++;

    // Get the most recent user message
    const lastUserMessage = [...messages].reverse().find((m) => m.role === 'user');

    const rawContent = lastUserMessage?.content ?? '';
    const content =
      typeof rawContent === 'string'
        ? rawContent
        : rawContent.map((c) => (c.type === 'text' ? c.text : '')).join('');

    // Try to match a scenario
    if (!this.currentScenario || this.scenarioIndex >= this.currentScenario.responses.length) {
      // Find a new scenario
      this.currentScenario = SCENARIOS.find((s) => s.trigger.test(content)) ?? null;
      this.scenarioIndex = 0;
    }

    let response: string;

    if (this.currentScenario && this.scenarioIndex < this.currentScenario.responses.length) {
      response = this.currentScenario.responses[this.scenarioIndex];
      this.scenarioIndex++;
    } else {
      // Default response
      response = `I understand. Let me help you with that.

Based on the context, here's my analysis:
- The task appears to be: ${content.slice(0, 50)}...
- I've processed the request successfully.

Is there anything specific you'd like me to clarify?`;
    }

    return {
      content: response,
      stopReason: 'end_turn',
      usage: {
        inputTokens: estimateTokenCount(content),
        outputTokens: estimateTokenCount(response),
      },
    };
  }

  /**
   * Chat with tool use support.
   * Uses configured tool responses if available, falls back to chat().
   */
  async chatWithTools(
    messages: (Message | MessageWithContent)[],
    options?: ChatOptionsWithTools,
  ): Promise<ChatResponseWithTools> {
    // If tool responses are configured, use them
    if (this.toolResponses.length > 0) {
      await new Promise((resolve) => setTimeout(resolve, 50));
      this.callCount++;

      const idx = this.toolResponseIndex % this.toolResponses.length;
      this.toolResponseIndex++;
      const preset = this.toolResponses[idx];

      return {
        content: preset.content,
        stopReason: preset.toolCalls ? 'end_turn' : 'end_turn',
        usage: {
          inputTokens: 100,
          outputTokens: 50,
        },
        toolCalls: preset.toolCalls,
      };
    }

    // Fall back to basic chat (no tool calls)
    const chatResponse = await this.chat(messages, options);
    return {
      ...chatResponse,
      toolCalls: undefined,
    };
  }

  /**
   * Configure mock tool responses for testing.
   */
  setToolResponses(responses: Array<{ content: string; toolCalls?: ToolCallResponse[] }>): void {
    this.toolResponses = responses;
    this.toolResponseIndex = 0;
  }

  /**
   * Reset the mock state for testing.
   */
  reset(): void {
    this.callCount = 0;
    this.currentScenario = null;
    this.scenarioIndex = 0;
    this.toolResponses = [];
    this.toolResponseIndex = 0;
  }

  /**
   * Get the number of calls made.
   */
  getCallCount(): number {
    return this.callCount;
  }
}

// =============================================================================
// REGISTRATION
// =============================================================================

registerProvider('mock', {
  priority: 100, // Lowest priority - only use if nothing else is configured
  detect: () => true, // Always available
  create: async () => new MockProvider(),
});
