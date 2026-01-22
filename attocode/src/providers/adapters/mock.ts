/**
 * Mock Provider
 * 
 * A mock LLM provider for testing and demonstration.
 * Always available as a fallback.
 */

import type { 
  LLMProvider, 
  Message, 
  ChatOptions, 
  ChatResponse 
} from '../types.js';
import { registerProvider } from '../provider.js';

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
      "Here are the files I found in the directory.",
    ],
  },
  {
    trigger: /read|show.*content|what.*in/i,
    responses: [
      `I'll read that file for you.

\`\`\`json
{ "tool": "read_file", "input": { "path": "package.json" } }
\`\`\``,
      "Here are the contents of the file.",
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

export class MockProvider implements LLMProvider {
  readonly name = 'mock';
  readonly defaultModel = 'mock-model';
  
  private callCount = 0;
  private currentScenario: MockScenario | null = null;
  private scenarioIndex = 0;

  isConfigured(): boolean {
    return true; // Always available
  }

  async chat(messages: Message[], _options?: ChatOptions): Promise<ChatResponse> {
    // Simulate network latency
    await new Promise(resolve => setTimeout(resolve, 100));
    
    this.callCount++;
    
    // Get the most recent user message
    const lastUserMessage = [...messages]
      .reverse()
      .find(m => m.role === 'user');
    
    const content = lastUserMessage?.content ?? '';
    
    // Try to match a scenario
    if (!this.currentScenario || this.scenarioIndex >= this.currentScenario.responses.length) {
      // Find a new scenario
      this.currentScenario = SCENARIOS.find(s => s.trigger.test(content)) ?? null;
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
        inputTokens: content.length / 4,
        outputTokens: response.length / 4,
      },
    };
  }

  /**
   * Reset the mock state for testing.
   */
  reset(): void {
    this.callCount = 0;
    this.currentScenario = null;
    this.scenarioIndex = 0;
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
