/**
 * Unit tests for Prompt Cache Markers (Improvement P1).
 *
 * Tests CacheableContentBlock generation from CacheAwareContext
 * and ContextEngineering, ensuring cache_control markers are
 * placed on static sections but not on dynamic content.
 */

import { describe, it, expect } from 'vitest';
import {
  CacheAwareContext,
} from '../../src/tricks/kv-cache-context.js';
import { createContextEngineering } from '../../src/integrations/context/context-engineering.js';

describe('CacheAwareContext.buildCacheableSystemPrompt', () => {
  function createContext(staticPrefix = 'You are a helpful assistant.') {
    return new CacheAwareContext({ staticPrefix });
  }

  it('should create blocks with cache_control markers for static content', () => {
    const ctx = createContext('System prefix.');
    const blocks = ctx.buildCacheableSystemPrompt({
      rules: 'Follow these rules.',
      tools: 'read_file, write_file',
    });

    // Static prefix — cached
    expect(blocks[0]).toEqual({
      type: 'text',
      text: 'System prefix.',
      cache_control: { type: 'ephemeral' },
    });

    // Rules — cached
    expect(blocks[1]).toEqual({
      type: 'text',
      text: expect.stringContaining('Follow these rules.'),
      cache_control: { type: 'ephemeral' },
    });

    // Tools — cached
    expect(blocks[2]).toEqual({
      type: 'text',
      text: expect.stringContaining('read_file, write_file'),
      cache_control: { type: 'ephemeral' },
    });
  });

  it('should NOT add cache_control to dynamic content', () => {
    const ctx = createContext('Prefix.');
    const blocks = ctx.buildCacheableSystemPrompt({
      dynamic: { sessionId: 'abc-123', timestamp: '2026-01-01' },
    });

    // Find the dynamic block (last one)
    const dynamicBlock = blocks.find(b => b.text.includes('Session:'));
    expect(dynamicBlock).toBeDefined();
    expect(dynamicBlock!.cache_control).toBeUndefined();
  });

  it('should include memory block with cache marker', () => {
    const ctx = createContext('Prefix.');
    const blocks = ctx.buildCacheableSystemPrompt({
      memory: 'User prefers TypeScript.',
    });

    const memoryBlock = blocks.find(b => b.text.includes('User prefers TypeScript'));
    expect(memoryBlock).toBeDefined();
    expect(memoryBlock!.cache_control).toEqual({ type: 'ephemeral' });
  });

  it('should return empty array when no content provided', () => {
    const ctx = createContext('');
    const blocks = ctx.buildCacheableSystemPrompt({});

    // Empty staticPrefix produces no block, and no options → empty
    expect(blocks.length).toBe(0);
  });

  it('should order blocks: static > rules > tools > memory > dynamic', () => {
    const ctx = createContext('Prefix.');
    const blocks = ctx.buildCacheableSystemPrompt({
      rules: 'Rules.',
      tools: 'Tools.',
      memory: 'Memory.',
      dynamic: { mode: 'plan' },
    });

    expect(blocks.length).toBe(5);
    expect(blocks[0].text).toBe('Prefix.');
    expect(blocks[1].text).toContain('Rules.');
    expect(blocks[2].text).toContain('Tools.');
    expect(blocks[3].text).toContain('Memory.');
    expect(blocks[4].text).toContain('Mode:');
    expect(blocks[4].cache_control).toBeUndefined(); // Dynamic = not cached
  });

  it('should include only provided sections', () => {
    const ctx = createContext('Prefix.');
    const blocks = ctx.buildCacheableSystemPrompt({
      tools: 'read_file',
    });

    // Should have: prefix + tools = 2 blocks
    expect(blocks.length).toBe(2);
    expect(blocks[0].text).toBe('Prefix.');
    expect(blocks[1].text).toContain('read_file');
  });
});

describe('ContextEngineeringManager.buildCacheableSystemPrompt', () => {
  it('should return empty array when cache context is not configured', () => {
    const ce = createContextEngineering({
      staticPrefix: 'Hello.',
      enableCacheOptimization: false, // No KV-cache
    });

    const blocks = ce.buildCacheableSystemPrompt({
      rules: 'Some rules.',
    });

    // Should return empty (no cache context available)
    expect(blocks).toEqual([]);
  });

  it('should return blocks with markers when cache context is configured', () => {
    const ce = createContextEngineering({
      staticPrefix: 'Hello.',
      enableCacheOptimization: true,
    });

    const blocks = ce.buildCacheableSystemPrompt({
      rules: 'Some rules.',
      tools: 'Some tools.',
    });

    // Should have blocks with cache_control
    expect(blocks.length).toBeGreaterThan(0);
    const cachedBlocks = blocks.filter((b: { cache_control?: unknown }) => b.cache_control);
    expect(cachedBlocks.length).toBeGreaterThan(0);
  });
});
