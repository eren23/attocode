/**
 * Exercise Tests: Lesson 6 - Fixture Recorder
 *
 * Run with: npm run test:lesson:6:exercise
 */

import { describe, it, expect } from 'vitest';

// Import from answers for testing
import {
  FixtureRecorder,
  hashRequest,
  type ChatRequest,
  type ChatResponse,
} from './exercises/answers/exercise-1.js';

// =============================================================================
// TEST DATA
// =============================================================================

const sampleRequest: ChatRequest = {
  messages: [
    { role: 'system', content: 'You are helpful.' },
    { role: 'user', content: 'Hello' },
  ],
  model: 'test-model',
};

const sampleResponse: ChatResponse = {
  content: 'Hello! How can I help?',
  stopReason: 'end_turn',
  usage: { inputTokens: 10, outputTokens: 8 },
};

// =============================================================================
// TESTS: hashRequest
// =============================================================================

describe('hashRequest', () => {
  it('should produce consistent hash for same request', () => {
    const hash1 = hashRequest(sampleRequest);
    const hash2 = hashRequest(sampleRequest);

    expect(hash1).toBe(hash2);
  });

  it('should produce different hash for different requests', () => {
    const request2: ChatRequest = {
      ...sampleRequest,
      messages: [{ role: 'user', content: 'Different' }],
    };

    const hash1 = hashRequest(sampleRequest);
    const hash2 = hashRequest(request2);

    expect(hash1).not.toBe(hash2);
  });

  it('should handle requests without optional fields', () => {
    const minimalRequest: ChatRequest = {
      messages: [{ role: 'user', content: 'Hi' }],
    };

    const hash = hashRequest(minimalRequest);
    expect(typeof hash).toBe('string');
    expect(hash.length).toBeGreaterThan(0);
  });
});

// =============================================================================
// TESTS: FixtureRecorder - Record Mode
// =============================================================================

describe('FixtureRecorder - Record Mode', () => {
  it('should create in record mode', () => {
    const recorder = new FixtureRecorder('record');
    expect(recorder.getMode()).toBe('record');
  });

  it('should record request/response pairs', async () => {
    const recorder = new FixtureRecorder('record');

    await recorder.record(sampleRequest, sampleResponse);

    expect(recorder.getFixtureCount()).toBe(1);
  });

  it('should record multiple fixtures', async () => {
    const recorder = new FixtureRecorder('record');

    const request2: ChatRequest = {
      messages: [{ role: 'user', content: 'Second' }],
    };
    const response2: ChatResponse = {
      content: 'Second response',
      stopReason: 'end_turn',
    };

    await recorder.record(sampleRequest, sampleResponse);
    await recorder.record(request2, response2);

    expect(recorder.getFixtureCount()).toBe(2);
  });

  it('should overwrite duplicate requests', async () => {
    const recorder = new FixtureRecorder('record');

    const response2: ChatResponse = {
      content: 'Updated response',
      stopReason: 'end_turn',
    };

    await recorder.record(sampleRequest, sampleResponse);
    await recorder.record(sampleRequest, response2);

    expect(recorder.getFixtureCount()).toBe(1);
  });

  it('should throw when calling playback in record mode', async () => {
    const recorder = new FixtureRecorder('record');

    await expect(recorder.playback(sampleRequest)).rejects.toThrow();
  });
});

// =============================================================================
// TESTS: FixtureRecorder - Playback Mode
// =============================================================================

describe('FixtureRecorder - Playback Mode', () => {
  it('should create in playback mode', () => {
    const recorder = new FixtureRecorder('playback');
    expect(recorder.getMode()).toBe('playback');
  });

  it('should return null for unknown request', async () => {
    const recorder = new FixtureRecorder('playback');

    const response = await recorder.playback(sampleRequest);

    expect(response).toBeNull();
  });

  it('should throw when calling record in playback mode', async () => {
    const recorder = new FixtureRecorder('playback');

    await expect(recorder.record(sampleRequest, sampleResponse)).rejects.toThrow();
  });
});

// =============================================================================
// TESTS: FixtureRecorder - Serialization
// =============================================================================

describe('FixtureRecorder - Serialization', () => {
  it('should serialize to JSON', async () => {
    const recorder = new FixtureRecorder('record');
    await recorder.record(sampleRequest, sampleResponse);

    const json = recorder.toJSON();

    expect(typeof json).toBe('string');
    expect(() => JSON.parse(json)).not.toThrow();
  });

  it('should deserialize from JSON', async () => {
    const recorder = new FixtureRecorder('record');
    await recorder.record(sampleRequest, sampleResponse);

    const json = recorder.toJSON();
    const loaded = FixtureRecorder.fromJSON(json);

    expect(loaded.getMode()).toBe('playback');
    expect(loaded.getFixtureCount()).toBe(1);
  });

  it('should play back recorded fixtures after deserialization', async () => {
    // Record
    const recorder = new FixtureRecorder('record');
    await recorder.record(sampleRequest, sampleResponse);

    // Serialize and deserialize
    const json = recorder.toJSON();
    const loaded = FixtureRecorder.fromJSON(json);

    // Playback
    const response = await loaded.playback(sampleRequest);

    expect(response).toEqual(sampleResponse);
  });

  it('should handle empty fixtures', () => {
    const recorder = new FixtureRecorder('record');
    const json = recorder.toJSON();
    const loaded = FixtureRecorder.fromJSON(json);

    expect(loaded.getFixtureCount()).toBe(0);
  });

  it('should preserve multiple fixtures through serialization', async () => {
    const recorder = new FixtureRecorder('record');

    const requests = [
      { messages: [{ role: 'user' as const, content: 'One' }] },
      { messages: [{ role: 'user' as const, content: 'Two' }] },
      { messages: [{ role: 'user' as const, content: 'Three' }] },
    ];

    for (let i = 0; i < requests.length; i++) {
      await recorder.record(requests[i], {
        content: `Response ${i}`,
        stopReason: 'end_turn',
      });
    }

    const json = recorder.toJSON();
    const loaded = FixtureRecorder.fromJSON(json);

    expect(loaded.getFixtureCount()).toBe(3);

    // Verify all can be played back
    for (let i = 0; i < requests.length; i++) {
      const response = await loaded.playback(requests[i]);
      expect(response?.content).toBe(`Response ${i}`);
    }
  });
});
