/**
 * Lesson 6: Mock Providers
 * 
 * Mock LLM providers for deterministic testing.
 */

// =============================================================================
// TYPES
// =============================================================================

export interface Message {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

export interface ChatOptions {
  maxTokens?: number;
  temperature?: number;
  model?: string;
}

export interface ChatResponse {
  content: string;
  stopReason: 'end_turn' | 'max_tokens' | 'tool_use';
}

export interface LLMProvider {
  readonly name: string;
  chat(messages: Message[], options?: ChatOptions): Promise<ChatResponse>;
}

/**
 * Record of an LLM call for verification.
 */
export interface CallRecord {
  messages: Message[];
  options?: ChatOptions;
  response: ChatResponse;
  timestamp: Date;
  containedToolCall?: string;
}

/**
 * Scripted response for mock provider.
 */
export interface ScriptedResponse {
  /** The response content */
  response: string;
  
  /** Stop reason (default: 'end_turn' or 'tool_use' if response contains tool call) */
  stopReason?: ChatResponse['stopReason'];
  
  /** Delay before responding (ms) */
  delay?: number;
  
  /** Error to throw instead of responding */
  error?: Error;
  
  /** Condition: only use this response if messages contain this text */
  when?: string | RegExp;
  
  /** Assert: the input must contain this text */
  mustContain?: string | RegExp;
}

// =============================================================================
// SCRIPTED LLM PROVIDER
// =============================================================================

/**
 * Mock LLM that returns scripted responses.
 * Useful for testing specific conversation flows.
 */
export class ScriptedLLMProvider implements LLMProvider {
  readonly name = 'scripted-mock';
  
  private responses: ScriptedResponse[];
  private responseIndex = 0;
  private callLog: CallRecord[] = [];

  constructor(responses: ScriptedResponse[]) {
    this.responses = responses;
  }

  async chat(messages: Message[], options?: ChatOptions): Promise<ChatResponse> {
    // Find the next applicable response
    let response = this.findNextResponse(messages);
    
    if (!response) {
      throw new Error(`ScriptedLLMProvider: No more responses (called ${this.callLog.length + 1} times, only ${this.responses.length} responses defined)`);
    }

    // Check mustContain assertion
    if (response.mustContain) {
      const allText = messages.map(m => m.content).join(' ');
      const pattern = typeof response.mustContain === 'string' 
        ? new RegExp(response.mustContain) 
        : response.mustContain;
      
      if (!pattern.test(allText)) {
        throw new Error(`ScriptedLLMProvider assertion failed: messages must contain ${response.mustContain}`);
      }
    }

    // Simulate delay
    if (response.delay) {
      await new Promise(resolve => setTimeout(resolve, response.delay));
    }

    // Throw error if specified
    if (response.error) {
      throw response.error;
    }

    // Determine stop reason
    let stopReason = response.stopReason;
    if (!stopReason) {
      stopReason = this.detectToolCall(response.response) ? 'tool_use' : 'end_turn';
    }

    const chatResponse: ChatResponse = {
      content: response.response,
      stopReason,
    };

    // Record the call
    const toolCall = this.detectToolCall(response.response);
    this.callLog.push({
      messages: [...messages],
      options,
      response: chatResponse,
      timestamp: new Date(),
      containedToolCall: toolCall ?? undefined,
    });

    this.responseIndex++;
    return chatResponse;
  }

  /**
   * Find the next response that matches the messages.
   */
  private findNextResponse(messages: Message[]): ScriptedResponse | null {
    const allText = messages.map(m => m.content).join(' ');

    // First, try to find a conditional response
    for (let i = this.responseIndex; i < this.responses.length; i++) {
      const response = this.responses[i];
      if (response.when) {
        const pattern = typeof response.when === 'string' 
          ? new RegExp(response.when) 
          : response.when;
        
        if (pattern.test(allText)) {
          // Found a matching conditional response
          return response;
        }
      }
    }

    // Fall back to sequential response
    if (this.responseIndex < this.responses.length) {
      return this.responses[this.responseIndex];
    }

    return null;
  }

  /**
   * Detect tool call in response.
   */
  private detectToolCall(response: string): string | null {
    const patterns = [
      /```json\s*\{\s*"tool"\s*:\s*"([^"]+)"/,
      /"tool"\s*:\s*"([^"]+)"/,
    ];

    for (const pattern of patterns) {
      const match = response.match(pattern);
      if (match) {
        return match[1];
      }
    }

    return null;
  }

  /**
   * Get the call log for verification.
   */
  getCallLog(): CallRecord[] {
    return [...this.callLog];
  }

  /**
   * Get number of calls made.
   */
  getCallCount(): number {
    return this.callLog.length;
  }

  /**
   * Reset the provider for reuse.
   */
  reset(): void {
    this.responseIndex = 0;
    this.callLog = [];
  }

  /**
   * Verify all responses were used.
   */
  verifyAllResponsesUsed(): void {
    if (this.responseIndex < this.responses.length) {
      throw new Error(
        `ScriptedLLMProvider: Only ${this.responseIndex} of ${this.responses.length} responses were used`
      );
    }
  }
}

// =============================================================================
// ECHO LLM PROVIDER
// =============================================================================

/**
 * Mock LLM that echoes back a transformation of the input.
 * Useful for testing parsing and tool execution.
 */
export class EchoLLMProvider implements LLMProvider {
  readonly name = 'echo-mock';
  
  private transform: (messages: Message[]) => string;
  private callLog: CallRecord[] = [];

  constructor(transform?: (messages: Message[]) => string) {
    this.transform = transform ?? ((messages) => {
      const lastUser = messages.filter(m => m.role === 'user').pop();
      return `You said: ${lastUser?.content ?? 'nothing'}`;
    });
  }

  async chat(messages: Message[], options?: ChatOptions): Promise<ChatResponse> {
    const content = this.transform(messages);
    const response: ChatResponse = {
      content,
      stopReason: 'end_turn',
    };

    this.callLog.push({
      messages: [...messages],
      options,
      response,
      timestamp: new Date(),
    });

    return response;
  }

  getCallLog(): CallRecord[] {
    return [...this.callLog];
  }
}

// =============================================================================
// RECORDING LLM PROVIDER
// =============================================================================

/**
 * Wraps another provider and records all interactions.
 * Useful for creating fixtures from real conversations.
 */
export class RecordingLLMProvider implements LLMProvider {
  readonly name: string;
  
  private inner: LLMProvider;
  private recordings: Array<{
    input: { messages: Message[]; options?: ChatOptions };
    output: ChatResponse;
    error?: Error;
  }> = [];

  constructor(inner: LLMProvider) {
    this.inner = inner;
    this.name = `recording-${inner.name}`;
  }

  async chat(messages: Message[], options?: ChatOptions): Promise<ChatResponse> {
    const input = { messages: [...messages], options };
    
    try {
      const output = await this.inner.chat(messages, options);
      this.recordings.push({ input, output });
      return output;
    } catch (error) {
      this.recordings.push({ input, output: { content: '', stopReason: 'end_turn' }, error: error as Error });
      throw error;
    }
  }

  /**
   * Export recordings as fixture JSON.
   */
  exportFixture(): string {
    return JSON.stringify(this.recordings, null, 2);
  }

  /**
   * Get recordings.
   */
  getRecordings(): typeof this.recordings {
    return [...this.recordings];
  }
}

// =============================================================================
// FIXTURE-BASED LLM PROVIDER
// =============================================================================

/**
 * Replays recorded conversations from a fixture.
 */
export class FixtureLLMProvider implements LLMProvider {
  readonly name = 'fixture-mock';
  
  private fixture: Array<{
    input: { messages: Message[]; options?: ChatOptions };
    output: ChatResponse;
  }>;
  private index = 0;

  constructor(fixture: typeof FixtureLLMProvider.prototype.fixture) {
    this.fixture = fixture;
  }

  /**
   * Load from JSON file content.
   */
  static fromJSON(json: string): FixtureLLMProvider {
    try {
      const fixture = JSON.parse(json);
      return new FixtureLLMProvider(fixture);
    } catch (error) {
      throw new Error(`Failed to parse fixture JSON: ${(error as Error).message}`);
    }
  }

  async chat(messages: Message[], options?: ChatOptions): Promise<ChatResponse> {
    if (this.index >= this.fixture.length) {
      throw new Error('FixtureLLMProvider: Fixture exhausted');
    }

    const recording = this.fixture[this.index++];
    return recording.output;
  }

  /**
   * Reset to beginning.
   */
  reset(): void {
    this.index = 0;
  }
}
