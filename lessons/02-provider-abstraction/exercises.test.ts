/**
 * Exercise Tests: Lesson 2 - Delayed Mock Provider
 *
 * Run with: npm run test:lesson:2:exercise
 */

import { describe, it, expect, beforeEach } from 'vitest';

// Import from answers for testing
import {
  DelayedMockProvider,
  type LLMProvider,
} from './exercises/answers/exercise-1.js';

describe('DelayedMockProvider', () => {
  describe('interface compliance', () => {
    it('should implement LLMProvider interface', () => {
      const provider = new DelayedMockProvider({
        responses: ['test'],
      });

      // Check required properties exist
      expect(provider.name).toBeDefined();
      expect(provider.defaultModel).toBeDefined();
      expect(typeof provider.chat).toBe('function');
      expect(typeof provider.isConfigured).toBe('function');
    });

    it('should have correct name property', () => {
      const provider = new DelayedMockProvider({
        responses: ['test'],
        name: 'custom-mock',
      });

      expect(provider.name).toBe('custom-mock');
    });

    it('should use default name when not specified', () => {
      const provider = new DelayedMockProvider({
        responses: ['test'],
      });

      expect(provider.name).toBe('delayed-mock');
    });
  });

  describe('chat method', () => {
    it('should return responses in order', async () => {
      const provider = new DelayedMockProvider({
        responses: ['First', 'Second', 'Third'],
      });

      const r1 = await provider.chat([{ role: 'user', content: 'hi' }]);
      const r2 = await provider.chat([{ role: 'user', content: 'hi' }]);
      const r3 = await provider.chat([{ role: 'user', content: 'hi' }]);

      expect(r1.content).toBe('First');
      expect(r2.content).toBe('Second');
      expect(r3.content).toBe('Third');
    });

    it('should return valid ChatResponse structure', async () => {
      const provider = new DelayedMockProvider({
        responses: ['Hello'],
      });

      const response = await provider.chat([{ role: 'user', content: 'hi' }]);

      expect(response).toHaveProperty('content');
      expect(response).toHaveProperty('stopReason');
      expect(response.stopReason).toBe('end_turn');
    });

    it('should throw when responses exhausted', async () => {
      const provider = new DelayedMockProvider({
        responses: ['Only one'],
      });

      await provider.chat([{ role: 'user', content: 'first' }]);

      await expect(
        provider.chat([{ role: 'user', content: 'second' }])
      ).rejects.toThrow(/exhausted/i);
    });

    it('should add delay before response', async () => {
      const delayMs = 50;
      const provider = new DelayedMockProvider({
        responses: ['delayed'],
        delayMs,
      });

      const start = Date.now();
      await provider.chat([{ role: 'user', content: 'hi' }]);
      const elapsed = Date.now() - start;

      // Allow some tolerance for timing
      expect(elapsed).toBeGreaterThanOrEqual(delayMs - 10);
    });
  });

  describe('isConfigured method', () => {
    it('should return true when responses are provided', () => {
      const provider = new DelayedMockProvider({
        responses: ['test'],
      });

      expect(provider.isConfigured()).toBe(true);
    });

    it('should return false when responses array is empty', () => {
      const provider = new DelayedMockProvider({
        responses: [],
      });

      expect(provider.isConfigured()).toBe(false);
    });
  });

  describe('statistics tracking', () => {
    let provider: DelayedMockProvider;

    beforeEach(() => {
      provider = new DelayedMockProvider({
        responses: ['a', 'b', 'c'],
        delayMs: 10,
      });
    });

    it('should track call count', async () => {
      expect(provider.getStats().callCount).toBe(0);

      await provider.chat([{ role: 'user', content: '1' }]);
      expect(provider.getStats().callCount).toBe(1);

      await provider.chat([{ role: 'user', content: '2' }]);
      expect(provider.getStats().callCount).toBe(2);
    });

    it('should track total delay', async () => {
      await provider.chat([{ role: 'user', content: '1' }]);
      await provider.chat([{ role: 'user', content: '2' }]);

      const stats = provider.getStats();
      expect(stats.totalDelayMs).toBe(20);
    });

    it('should return copy of stats (not reference)', () => {
      const stats1 = provider.getStats();
      const stats2 = provider.getStats();

      expect(stats1).not.toBe(stats2);
      expect(stats1).toEqual(stats2);
    });
  });

  describe('reset method', () => {
    it('should reset response index', async () => {
      const provider = new DelayedMockProvider({
        responses: ['first', 'second'],
      });

      await provider.chat([{ role: 'user', content: 'hi' }]);
      expect((await provider.chat([{ role: 'user', content: 'hi' }])).content).toBe('second');

      provider.reset();

      expect((await provider.chat([{ role: 'user', content: 'hi' }])).content).toBe('first');
    });

    it('should reset stats', async () => {
      const provider = new DelayedMockProvider({
        responses: ['test', 'test'],
        delayMs: 5,
      });

      await provider.chat([{ role: 'user', content: 'hi' }]);
      expect(provider.getStats().callCount).toBe(1);

      provider.reset();

      expect(provider.getStats().callCount).toBe(0);
      expect(provider.getStats().totalDelayMs).toBe(0);
    });
  });
});
