/**
 * AutoCompaction Tests
 *
 * Tests for AutoCompactionManager including integration with reversible compaction.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  AutoCompactionManager,
  createAutoCompactionManager,
  type AutoCompactionConfig,
} from '../src/integrations/context/auto-compaction.js';
import { Compactor, createCompactor } from '../src/integrations/context/compaction.js';
import type { Message } from '../src/types.js';

// =============================================================================
// MOCK COMPACTOR
// =============================================================================

function createMockCompactor(options?: {
  tokenEstimate?: number;
  compactResult?: { summary: string; tokensBefore: number; tokensAfter: number };
}): Compactor {
  const tokenEstimate = options?.tokenEstimate ?? 50000;
  const compactResult = options?.compactResult ?? {
    summary: 'Mocked summary',
    tokensBefore: 100000,
    tokensAfter: 30000,
  };

  return {
    compact: vi.fn().mockResolvedValue({
      ...compactResult,
      preservedMessages: [{ role: 'assistant', content: compactResult.summary }],
    }),
    estimateTokens: vi.fn().mockReturnValue(tokenEstimate),
    getConfig: vi.fn().mockReturnValue({ preserveRecentCount: 10 }),
    updateConfig: vi.fn(),
  } as unknown as Compactor;
}

// =============================================================================
// BASIC FUNCTIONALITY TESTS
// =============================================================================

describe('AutoCompactionManager', () => {
  describe('threshold detection', () => {
    it('should return ok when below warning threshold', async () => {
      const compactor = createMockCompactor({ tokenEstimate: 100000 });
      const manager = createAutoCompactionManager(compactor, {
        maxContextTokens: 200000,
        warningThreshold: 0.80,
      });

      const result = await manager.checkAndMaybeCompact({
        currentTokens: 100000, // 50% - below warning
        messages: [],
      });

      expect(result.status).toBe('ok');
      expect(result.ratio).toBe(0.5);
    });

    it('should return warning when in warning zone', async () => {
      const compactor = createMockCompactor({ tokenEstimate: 170000 });
      const manager = createAutoCompactionManager(compactor, {
        maxContextTokens: 200000,
        warningThreshold: 0.80,
        autoCompactThreshold: 0.90,
      });

      const result = await manager.checkAndMaybeCompact({
        currentTokens: 170000, // 85% - in warning zone
        messages: [],
      });

      expect(result.status).toBe('warning');
    });

    it('should trigger compaction when above auto-compact threshold in auto mode', async () => {
      const compactor = createMockCompactor({
        tokenEstimate: 185000,
        compactResult: {
          summary: 'Compacted summary',
          tokensBefore: 185000,
          tokensAfter: 50000,
        },
      });
      const manager = createAutoCompactionManager(compactor, {
        mode: 'auto',
        maxContextTokens: 200000,
        autoCompactThreshold: 0.90,
        cooldownMs: 0, // Disable cooldown for test
      });

      const messages: Message[] = [
        { role: 'user', content: 'Hello' },
        { role: 'assistant', content: 'Hi there!' },
      ];

      const result = await manager.checkAndMaybeCompact({
        currentTokens: 185000, // 92.5% - above auto-compact threshold
        messages,
      });

      expect(result.status).toBe('compacted');
      expect(compactor.compact).toHaveBeenCalled();
    });
  });

  describe('events', () => {
    it('should emit events during compaction', async () => {
      const compactor = createMockCompactor({
        tokenEstimate: 185000,
        compactResult: {
          summary: 'Compacted',
          tokensBefore: 185000,
          tokensAfter: 50000,
        },
      });
      const manager = createAutoCompactionManager(compactor, {
        mode: 'auto',
        maxContextTokens: 200000,
        autoCompactThreshold: 0.90,
        cooldownMs: 0,
      });

      const events: Array<{ type: string }> = [];
      manager.on(event => events.push(event));

      await manager.checkAndMaybeCompact({
        currentTokens: 185000,
        messages: [],
      });

      const eventTypes = events.map(e => e.type);
      expect(eventTypes).toContain('autocompaction.check');
      expect(eventTypes).toContain('autocompaction.triggered');
      expect(eventTypes).toContain('autocompaction.completed');
    });
  });
});

// =============================================================================
// REVERSIBLE COMPACTION INTEGRATION TESTS
// =============================================================================

describe('AutoCompactionManager with custom compaction handler', () => {
  it('should use custom compaction handler when provided', async () => {
    const compactor = createMockCompactor({ tokenEstimate: 185000 });
    const customCompactFn = vi.fn().mockResolvedValue({
      summary: 'Custom compacted summary with references',
      tokensBefore: 185000,
      tokensAfter: 40000,
      preservedMessages: [{ role: 'assistant', content: 'Custom summary' }],
      references: [
        { type: 'file', value: '/src/main.ts', id: 'ref1' },
        { type: 'url', value: 'https://docs.example.com', id: 'ref2' },
      ],
    });

    const manager = createAutoCompactionManager(compactor, {
      mode: 'auto',
      maxContextTokens: 200000,
      autoCompactThreshold: 0.90,
      cooldownMs: 0,
      compactHandler: customCompactFn, // Custom handler for reversible compaction
    });

    const messages: Message[] = [
      { role: 'user', content: 'Read /src/main.ts' },
      { role: 'assistant', content: 'Here is the file content...' },
    ];

    const result = await manager.checkAndMaybeCompact({
      currentTokens: 185000,
      messages,
    });

    expect(result.status).toBe('compacted');
    expect(customCompactFn).toHaveBeenCalledWith(messages);
    // Default compactor should NOT have been called
    expect(compactor.compact).not.toHaveBeenCalled();
  });

  it('should fall back to default compactor when custom handler is not provided', async () => {
    const compactor = createMockCompactor({
      tokenEstimate: 185000,
      compactResult: {
        summary: 'Default compacted',
        tokensBefore: 185000,
        tokensAfter: 50000,
      },
    });

    const manager = createAutoCompactionManager(compactor, {
      mode: 'auto',
      maxContextTokens: 200000,
      autoCompactThreshold: 0.90,
      cooldownMs: 0,
      // No compactHandler - should use default
    });

    const result = await manager.checkAndMaybeCompact({
      currentTokens: 185000,
      messages: [],
    });

    expect(result.status).toBe('compacted');
    expect(compactor.compact).toHaveBeenCalled();
  });

  it('should preserve references in compaction result when using custom handler', async () => {
    const compactor = createMockCompactor({ tokenEstimate: 185000 });
    const references = [
      { type: 'file', value: '/src/agent.ts', id: 'ref1', timestamp: new Date().toISOString() },
      { type: 'function', value: 'handleCompaction', id: 'ref2', timestamp: new Date().toISOString() },
    ];

    const customCompactFn = vi.fn().mockResolvedValue({
      summary: 'Summary with preserved references',
      tokensBefore: 185000,
      tokensAfter: 40000,
      preservedMessages: [{ role: 'assistant', content: 'Summary' }],
      references,
    });

    const manager = createAutoCompactionManager(compactor, {
      mode: 'auto',
      maxContextTokens: 200000,
      autoCompactThreshold: 0.90,
      cooldownMs: 0,
      compactHandler: customCompactFn,
    });

    const result = await manager.checkAndMaybeCompact({
      currentTokens: 185000,
      messages: [],
    });

    expect(result.status).toBe('compacted');
    expect(result.references).toBeDefined();
    expect(result.references).toHaveLength(2);
    expect(result.references![0].type).toBe('file');
  });
});
