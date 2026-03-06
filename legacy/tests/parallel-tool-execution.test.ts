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
  CONDITIONALLY_PARALLEL_TOOLS,
  extractToolFilePath,
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

    // With conditional parallelism: write_file /c.ts has no conflict with reads /a.ts, /b.ts
    // read_file /d.ts is also parallel → all 4 tools in one batch
    expect(batches).toHaveLength(1);
    expect(batches[0]).toHaveLength(4);
  });

  it('should batch non-consecutive parallelizable tools across write barriers', () => {
    const toolCalls = [
      { name: 'read_file', path: '/a.ts' },
      { name: 'read_file', path: '/b.ts' },
      { name: 'bash', command: 'npm test' }, // bash is fully sequential (not conditionally parallel)
      { name: 'read_file', path: '/d.ts' },
      { name: 'grep', pattern: 'foo' },
    ];

    const batches = groupToolCallsIntoBatches(toolCalls);

    // [read_file, read_file] → [bash] → [read_file, grep]
    expect(batches).toHaveLength(3);
    expect(batches[0]).toHaveLength(2);
    expect(batches[2]).toHaveLength(2); // read_file + grep batched together
    expect(batches[2][0].name).toBe('read_file');
    expect(batches[2][1].name).toBe('grep');
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

  it('should parallelize writes to different files', () => {
    const toolCalls = [
      { name: 'write_file', path: '/a.ts', content: 'x' },
      { name: 'edit_file', path: '/b.ts' },
      { name: 'bash', command: 'npm test' },
    ];

    const batches = groupToolCallsIntoBatches(toolCalls);

    // write_file /a.ts and edit_file /b.ts target different files → parallel
    // bash is fully sequential → own batch
    expect(batches).toHaveLength(2);
    expect(batches[0]).toHaveLength(2);
    expect(batches[0][0].name).toBe('write_file');
    expect(batches[0][1].name).toBe('edit_file');
    expect(batches[1][0].name).toBe('bash');
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

  it('should handle alternating read-write-read-write on same files', () => {
    const toolCalls = [
      { name: 'read_file', path: '/a.ts' },
      { name: 'write_file', path: '/a.ts', content: 'modified' },
      { name: 'read_file', path: '/b.ts' },
      { name: 'edit_file', path: '/b.ts' },
    ];

    const batches = groupToolCallsIntoBatches(toolCalls);

    // read_file /a.ts → accumulator
    // write_file /a.ts → conditionally parallel, but /a.ts conflicts → flush [read_file], start [write_file /a.ts]
    // read_file /b.ts → parallel, add to accumulator → [write_file /a.ts, read_file /b.ts]
    // edit_file /b.ts → conditionally parallel, /b.ts conflicts with read_file /b.ts → flush, start [edit_file /b.ts]
    expect(batches).toHaveLength(3);
    expect(batches[0]).toHaveLength(1);
    expect(batches[0][0].name).toBe('read_file');
    expect(batches[1]).toHaveLength(2);
    expect(batches[1][0].name).toBe('write_file');
    expect(batches[1][1].name).toBe('read_file');
    expect(batches[2]).toHaveLength(1);
    expect(batches[2][0].name).toBe('edit_file');
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
      () => false, // disable conditional parallelism
    );

    expect(batches).toHaveLength(2);
    expect(batches[0]).toHaveLength(2);
    expect(batches[1]).toHaveLength(1);
  });
});

describe('CONDITIONALLY_PARALLEL_TOOLS', () => {
  it('should contain write_file and edit_file', () => {
    expect(CONDITIONALLY_PARALLEL_TOOLS.has('write_file')).toBe(true);
    expect(CONDITIONALLY_PARALLEL_TOOLS.has('edit_file')).toBe(true);
  });

  it('should not contain read-only tools', () => {
    expect(CONDITIONALLY_PARALLEL_TOOLS.has('read_file')).toBe(false);
    expect(CONDITIONALLY_PARALLEL_TOOLS.has('bash')).toBe(false);
  });
});

describe('extractToolFilePath', () => {
  it('should extract path from top-level args', () => {
    expect(extractToolFilePath({ name: 'write_file', path: '/a.ts' })).toBe('/a.ts');
    expect(extractToolFilePath({ name: 'edit_file', file_path: '/b.ts' })).toBe('/b.ts');
  });

  it('should extract path from nested input object', () => {
    expect(extractToolFilePath({ name: 'write_file', input: { path: '/c.ts' } })).toBe('/c.ts');
  });

  it('should return null if no path found', () => {
    expect(extractToolFilePath({ name: 'bash', command: 'ls' })).toBeNull();
  });
});

describe('Conditional parallelism - file conflict detection', () => {
  it('should parallelize writes to different files', () => {
    const toolCalls = [
      { name: 'write_file', path: '/a.ts', content: 'a' },
      { name: 'write_file', path: '/b.ts', content: 'b' },
      { name: 'write_file', path: '/c.ts', content: 'c' },
    ];

    const batches = groupToolCallsIntoBatches(toolCalls);

    // All target different files → single parallel batch
    expect(batches).toHaveLength(1);
    expect(batches[0]).toHaveLength(3);
  });

  it('should separate writes to the same file', () => {
    const toolCalls = [
      { name: 'write_file', path: '/a.ts', content: 'first' },
      { name: 'write_file', path: '/a.ts', content: 'second' },
    ];

    const batches = groupToolCallsIntoBatches(toolCalls);

    // Same file → must be sequential
    expect(batches).toHaveLength(2);
    expect(batches[0]).toHaveLength(1);
    expect(batches[1]).toHaveLength(1);
  });

  it('should mix reads and writes to different files in one batch', () => {
    const toolCalls = [
      { name: 'read_file', path: '/a.ts' },
      { name: 'write_file', path: '/b.ts', content: 'new' },
      { name: 'grep', pattern: 'foo' },
      { name: 'edit_file', path: '/c.ts' },
    ];

    const batches = groupToolCallsIntoBatches(toolCalls);

    // All different files/operations → single batch
    expect(batches).toHaveLength(1);
    expect(batches[0]).toHaveLength(4);
  });

  it('should flush on conflict then continue accumulating', () => {
    const toolCalls = [
      { name: 'write_file', path: '/a.ts', content: 'first' },
      { name: 'write_file', path: '/b.ts', content: 'x' },
      { name: 'write_file', path: '/a.ts', content: 'second' }, // conflict with first
      { name: 'write_file', path: '/c.ts', content: 'y' }, // no conflict with /a.ts (new batch)
    ];

    const batches = groupToolCallsIntoBatches(toolCalls);

    // [write /a, write /b] → conflict on /a → [write /a, write /c]
    expect(batches).toHaveLength(2);
    expect(batches[0]).toHaveLength(2);
    expect(batches[0][0].path).toBe('/a.ts');
    expect(batches[0][1].path).toBe('/b.ts');
    expect(batches[1]).toHaveLength(2);
    expect(batches[1][0].path).toBe('/a.ts');
    expect(batches[1][1].path).toBe('/c.ts');
  });

  it('should treat unknown file paths as conflicts (conservative)', () => {
    const toolCalls = [
      { name: 'write_file', content: 'no path' }, // no path → treated as conflict
      { name: 'write_file', content: 'also no path' },
    ];

    const batches = groupToolCallsIntoBatches(toolCalls);

    // Can't determine paths → sequential (conservative)
    expect(batches).toHaveLength(2);
  });
});
