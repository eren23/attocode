/**
 * Exercise 6: Fixture Recorder - REFERENCE SOLUTION
 */

// =============================================================================
// TYPES
// =============================================================================

export interface Message {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

export interface ChatRequest {
  messages: Message[];
  model?: string;
  temperature?: number;
}

export interface ChatResponse {
  content: string;
  stopReason: string;
  usage?: {
    inputTokens: number;
    outputTokens: number;
  };
}

export interface Fixture {
  requestHash: string;
  request: ChatRequest;
  response: ChatResponse;
  timestamp: number;
}

export type RecorderMode = 'record' | 'playback';

// =============================================================================
// HELPER
// =============================================================================

export function hashRequest(request: ChatRequest): string {
  const normalized = {
    messages: request.messages.map(m => ({
      role: m.role,
      content: m.content,
    })),
    model: request.model,
    temperature: request.temperature,
  };

  const str = JSON.stringify(normalized);
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    const char = str.charCodeAt(i);
    hash = ((hash << 5) - hash) + char;
    hash = hash & hash;
  }
  return hash.toString(16);
}

// =============================================================================
// SOLUTION: FixtureRecorder
// =============================================================================

export class FixtureRecorder {
  private mode: RecorderMode;
  private fixtures: Map<string, Fixture> = new Map();

  constructor(mode: RecorderMode) {
    this.mode = mode;
  }

  getMode(): RecorderMode {
    return this.mode;
  }

  async record(request: ChatRequest, response: ChatResponse): Promise<void> {
    if (this.mode !== 'record') {
      throw new Error('Cannot record in playback mode');
    }

    const requestHash = hashRequest(request);
    const fixture: Fixture = {
      requestHash,
      request,
      response,
      timestamp: Date.now(),
    };

    this.fixtures.set(requestHash, fixture);
  }

  async playback(request: ChatRequest): Promise<ChatResponse | null> {
    if (this.mode !== 'playback') {
      throw new Error('Cannot playback in record mode');
    }

    const requestHash = hashRequest(request);
    const fixture = this.fixtures.get(requestHash);

    return fixture ? fixture.response : null;
  }

  getFixtureCount(): number {
    return this.fixtures.size;
  }

  toJSON(): string {
    const fixturesArray = Array.from(this.fixtures.values());
    return JSON.stringify({
      version: 1,
      fixtures: fixturesArray,
    }, null, 2);
  }

  static fromJSON(json: string): FixtureRecorder {
    const data = JSON.parse(json);
    const recorder = new FixtureRecorder('playback');

    if (data.fixtures && Array.isArray(data.fixtures)) {
      for (const fixture of data.fixtures) {
        recorder.fixtures.set(fixture.requestHash, fixture);
      }
    }

    return recorder;
  }
}
