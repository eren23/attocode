/**
 * Exercise Tests: Lesson 9 - Context Tracker
 *
 * Run with: npm run test:lesson:9:exercise
 */

import { describe, it, expect, beforeEach } from 'vitest';

// Import from answers for testing
import {
  ContextTracker,
  estimateTokens,
  type Message,
  type ContextTrackerConfig,
} from './exercises/answers/exercise-1.js';

// =============================================================================
// TEST DATA
// =============================================================================

const defaultConfig: ContextTrackerConfig = {
  maxTokens: 8000,
  warningThreshold: 0.8,
};

const sampleMessages: Message[] = [
  { role: 'system', content: 'You are a helpful assistant.' },
  { role: 'user', content: 'Hello!' },
  { role: 'assistant', content: 'Hi there! How can I help you today?' },
];

// =============================================================================
// TESTS: estimateTokens helper
// =============================================================================

describe('estimateTokens', () => {
  it('should estimate tokens from character count', () => {
    expect(estimateTokens('test')).toBe(1);
    expect(estimateTokens('a'.repeat(100))).toBe(25);
  });
});

// =============================================================================
// TESTS: ContextTracker - message tracking
// =============================================================================

describe('ContextTracker - message tracking', () => {
  let tracker: ContextTracker;

  beforeEach(() => {
    tracker = new ContextTracker(defaultConfig);
  });

  it('should add messages', () => {
    tracker.addMessage(sampleMessages[0]);
    tracker.addMessage(sampleMessages[1]);

    expect(tracker.getMessages().length).toBe(2);
  });

  it('should track message tokens', () => {
    const message: Message = { role: 'user', content: 'a'.repeat(100) };
    tracker.addMessage(message);

    const stats = tracker.getStats();
    expect(stats.totalTokens).toBe(25); // 100 chars / 4
  });

  it('should return copy of messages', () => {
    tracker.addMessage(sampleMessages[0]);

    const messages1 = tracker.getMessages();
    const messages2 = tracker.getMessages();

    expect(messages1).not.toBe(messages2);
    expect(messages1).toEqual(messages2);
  });
});

// =============================================================================
// TESTS: ContextTracker - tool call tracking
// =============================================================================

describe('ContextTracker - tool call tracking', () => {
  let tracker: ContextTracker;

  beforeEach(() => {
    tracker = new ContextTracker(defaultConfig);
  });

  it('should track tool calls', () => {
    tracker.addToolCall('read_file', 100);
    tracker.addToolCall('write_file', 50);

    const stats = tracker.getStats();
    expect(stats.toolCallCount).toBe(2);
  });

  it('should track tool tokens', () => {
    tracker.addToolCall('search', 200);

    const stats = tracker.getStats();
    expect(stats.totalTokens).toBe(200);
  });

  it('should list unique tools used', () => {
    tracker.addToolCall('read_file', 100);
    tracker.addToolCall('write_file', 50);
    tracker.addToolCall('read_file', 80); // Duplicate

    const stats = tracker.getStats();
    expect(stats.toolsUsed).toContain('read_file');
    expect(stats.toolsUsed).toContain('write_file');
    expect(stats.toolsUsed.length).toBe(2);
  });
});

// =============================================================================
// TESTS: ContextTracker - statistics
// =============================================================================

describe('ContextTracker - statistics', () => {
  let tracker: ContextTracker;

  beforeEach(() => {
    tracker = new ContextTracker(defaultConfig);
  });

  it('should calculate context usage percentage', () => {
    // Add 4000 tokens worth (50% of 8000)
    tracker.addMessage({ role: 'user', content: 'a'.repeat(16000) }); // 4000 tokens

    const stats = tracker.getStats();
    expect(stats.contextUsagePercent).toBe(50);
  });

  it('should cap usage at 100%', () => {
    // Add more than max tokens
    tracker.addMessage({ role: 'user', content: 'a'.repeat(40000) }); // 10000 tokens

    const stats = tracker.getStats();
    expect(stats.contextUsagePercent).toBe(100);
  });

  it('should track elapsed time', async () => {
    await new Promise(resolve => setTimeout(resolve, 50));

    const stats = tracker.getStats();
    expect(stats.elapsedMs).toBeGreaterThanOrEqual(50);
  });

  it('should combine message and tool tokens', () => {
    tracker.addMessage({ role: 'user', content: 'a'.repeat(400) }); // 100 tokens
    tracker.addToolCall('test', 100); // 100 tokens

    const stats = tracker.getStats();
    expect(stats.totalTokens).toBe(200);
  });
});

// =============================================================================
// TESTS: ContextTracker - limit checking
// =============================================================================

describe('ContextTracker - limit checking', () => {
  let tracker: ContextTracker;

  beforeEach(() => {
    tracker = new ContextTracker(defaultConfig);
  });

  it('should return false when under threshold', () => {
    // Add 4000 tokens (50%, below 80% threshold)
    tracker.addMessage({ role: 'user', content: 'a'.repeat(16000) });

    expect(tracker.isNearLimit()).toBe(false);
  });

  it('should return true when at threshold', () => {
    // Add 6400 tokens (80%, at threshold)
    tracker.addMessage({ role: 'user', content: 'a'.repeat(25600) });

    expect(tracker.isNearLimit()).toBe(true);
  });

  it('should return true when over threshold', () => {
    // Add 7000 tokens (87.5%, over 80% threshold)
    tracker.addMessage({ role: 'user', content: 'a'.repeat(28000) });

    expect(tracker.isNearLimit()).toBe(true);
  });

  it('should calculate remaining tokens', () => {
    tracker.addMessage({ role: 'user', content: 'a'.repeat(4000) }); // 1000 tokens

    const remaining = tracker.getRemainingTokens();
    expect(remaining).toBe(7000); // 8000 - 1000
  });

  it('should not return negative remaining tokens', () => {
    tracker.addMessage({ role: 'user', content: 'a'.repeat(40000) }); // 10000 tokens

    const remaining = tracker.getRemainingTokens();
    expect(remaining).toBe(0);
  });
});

// =============================================================================
// TESTS: ContextTracker - reset
// =============================================================================

describe('ContextTracker - reset', () => {
  it('should clear all state on reset', () => {
    const tracker = new ContextTracker(defaultConfig);

    tracker.addMessage(sampleMessages[0]);
    tracker.addToolCall('test', 100);

    tracker.reset();

    const stats = tracker.getStats();
    expect(stats.messageCount).toBe(0);
    expect(stats.toolCallCount).toBe(0);
    expect(stats.totalTokens).toBe(0);
    expect(tracker.getMessages()).toEqual([]);
  });

  it('should reset elapsed time', async () => {
    const tracker = new ContextTracker(defaultConfig);

    await new Promise(resolve => setTimeout(resolve, 50));

    tracker.reset();

    const stats = tracker.getStats();
    expect(stats.elapsedMs).toBeLessThan(50);
  });
});
