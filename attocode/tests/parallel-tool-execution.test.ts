/**
 * Parallel Tool Execution Batching Tests
 *
 * Tests for the B1 parallel tool batching logic. Imports and tests the
 * groupToolCallsIntoBatches algorithm and PARALLELIZABLE_TOOLS set
 * directly from agent.ts to prevent drift.
 */

import { describe, it, expect } from 'vitest';
import {
  groupToolCallsIntoBatches,
  PARALLELIZABLE_TOOLS,
} from '../src/agent.js';

// =============================================================================
// TESTS
// =============================================================================

describe('PARALLELIZABLE_TOOLS', () => {
  it('should contain expected read-only tools', () => {
    const expected = [
      'read_file', 'glob', 'grep', 'list_files',
      'search_files', 'search_code', 'get_file_info',
    ];
    for (const tool of expected) {
      expect(PARALLELIZABLE_TOOLS.has(tool)).toBe(true);
    }
  });

  it('should not contain write tools', () => {
    expect(PARALLELIZABLE_TOOLS.has('write_file')).toBe(false);
    expect(PARALLELIZABLE_TOOLS.has('edit_file')).toBe(false);
    expect(PARALLELIZABLE_TOOLS.has('bash')).toBe(false);
  });
});

describe('groupToolCallsIntoBatches', () => {
  it('should group all-read tools into a single parallel batch', () => {
    const toolCalls = [
      { name: 'read_file', path: '/a.ts' },
      { name: 'read_file', path: '/b.ts' },
      { name: 'read_file', path: '/c.ts' },
    ];

    const batches = groupToolCallsIntoBatches(toolCalls);

    expect(batches).toHaveLength(1);
    expect(batches[0]).toHaveLength(3);
    expect(batches[0].map(t => t.name)).toEqual(['read_file', 'read_file', 'read_file']);
  });

  it('should split mixed read+write into separate batches', () => {
    const toolCalls = [
      { name: 'read_file', path: '/a.ts' },
      { name: 'read_file', path: '/b.ts' },
      { name: 'write_file', path: '/c.ts', content: 'x' },
      { name: 'read_file', path: '/d.ts' },
    ];

    const batches = groupToolCallsIntoBatches(toolCalls);

    // [read_file, read_file] → [write_file] → [read_file]
    expect(batches).toHaveLength(3);
    expect(batches[0]).toHaveLength(2);
    expect(batches[0][0].name).toBe('read_file');
    expect(batches[0][1].name).toBe('read_file');
    expect(batches[1]).toHaveLength(1);
    expect(batches[1][0].name).toBe('write_file');
    expect(batches[2]).toHaveLength(1);
    expect(batches[2][0].name).toBe('read_file');
  });

  it('should handle a single tool as a single batch of 1', () => {
    const toolCalls = [
      { name: 'bash', command: 'ls' },
    ];

    const batches = groupToolCallsIntoBatches(toolCalls);

    expect(batches).toHaveLength(1);
    expect(batches[0]).toHaveLength(1);
    expect(batches[0][0].name).toBe('bash');
  });

  it('should create separate batches for all-sequential tools', () => {
    const toolCalls = [
      { name: 'write_file', path: '/a.ts', content: 'x' },
      { name: 'edit_file', path: '/b.ts' },
      { name: 'bash', command: 'npm test' },
    ];

    const batches = groupToolCallsIntoBatches(toolCalls);

    // Each sequential tool is in its own batch
    expect(batches).toHaveLength(3);
    expect(batches[0][0].name).toBe('write_file');
    expect(batches[1][0].name).toBe('edit_file');
    expect(batches[2][0].name).toBe('bash');
  });

  it('should preserve order within parallel batches', () => {
    const toolCalls = [
      { name: 'read_file', path: '/first.ts' },
      { name: 'glob', pattern: '*.ts' },
      { name: 'grep', pattern: 'foo' },
      { name: 'list_files', dir: '/src' },
    ];

    const batches = groupToolCallsIntoBatches(toolCalls);

    expect(batches).toHaveLength(1);
    expect(batches[0]).toHaveLength(4);
    // Order preserved
    expect(batches[0][0].name).toBe('read_file');
    expect(batches[0][1].name).toBe('glob');
    expect(batches[0][2].name).toBe('grep');
    expect(batches[0][3].name).toBe('list_files');
  });

  it('should handle empty input', () => {
    const batches = groupToolCallsIntoBatches([]);
    expect(batches).toHaveLength(0);
  });

  it('should handle alternating read-write-read-write pattern', () => {
    const toolCalls = [
      { name: 'read_file', path: '/a.ts' },
      { name: 'write_file', path: '/a.ts', content: 'modified' },
      { name: 'read_file', path: '/b.ts' },
      { name: 'edit_file', path: '/b.ts' },
    ];

    const batches = groupToolCallsIntoBatches(toolCalls);

    // Each transition creates a new batch
    expect(batches).toHaveLength(4);
    expect(batches[0][0].name).toBe('read_file');
    expect(batches[1][0].name).toBe('write_file');
    expect(batches[2][0].name).toBe('read_file');
    expect(batches[3][0].name).toBe('edit_file');
  });

  it('should group mixed parallelizable tools together', () => {
    const toolCalls = [
      { name: 'read_file', path: '/a.ts' },
      { name: 'glob', pattern: '**/*.ts' },
      { name: 'grep', pattern: 'import' },
      { name: 'search_files', query: 'function' },
      { name: 'get_file_info', path: '/a.ts' },
    ];

    const batches = groupToolCallsIntoBatches(toolCalls);

    expect(batches).toHaveLength(1);
    expect(batches[0]).toHaveLength(5);
  });

  it('should accept a custom isParallelizable predicate', () => {
    const toolCalls = [
      { name: 'custom_read' },
      { name: 'custom_read' },
      { name: 'custom_write' },
    ];

    const batches = groupToolCallsIntoBatches(
      toolCalls,
      (tc) => tc.name === 'custom_read',
    );

    expect(batches).toHaveLength(2);
    expect(batches[0]).toHaveLength(2);
    expect(batches[1]).toHaveLength(1);
  });
});
