/**
 * Tests for Tool Executor helper functions (Phase 2.1)
 *
 * Tests pure utility functions exported from tool-executor.ts:
 * groupToolCallsIntoBatches, extractToolFilePath, summarizeToolResult,
 * formatToolArgsForPlan, extractChangeReasoning.
 */

import { describe, it, expect } from 'vitest';
import {
  groupToolCallsIntoBatches,
  extractToolFilePath,
  summarizeToolResult,
  formatToolArgsForPlan,
  extractChangeReasoning,
} from '../../src/core/tool-executor.js';

import type { Message } from '../../src/types.js';

// =============================================================================
// groupToolCallsIntoBatches
// =============================================================================

describe('groupToolCallsIntoBatches', () => {
  it('returns empty array for empty input', () => {
    expect(groupToolCallsIntoBatches([])).toEqual([]);
  });

  it('batches all-parallel tools together', () => {
    const tools = [
      { name: 'read_file', id: '1' },
      { name: 'glob', id: '2' },
      { name: 'read_file', id: '3' },
    ];
    const batches = groupToolCallsIntoBatches(tools);
    expect(batches).toHaveLength(1);
    expect(batches[0]).toHaveLength(3);
  });

  it('puts sequential (bash) tools in individual batches', () => {
    const tools = [
      { name: 'bash', id: '1' },
      { name: 'bash', id: '2' },
    ];
    const batches = groupToolCallsIntoBatches(tools);
    expect(batches).toHaveLength(2);
    expect(batches[0]).toHaveLength(1);
    expect(batches[1]).toHaveLength(1);
  });

  it('handles mixed parallel and sequential ordering', () => {
    const tools = [
      { name: 'read_file', id: '1' },
      { name: 'read_file', id: '2' },
      { name: 'bash', id: '3' },
      { name: 'glob', id: '4' },
    ];
    const batches = groupToolCallsIntoBatches(tools);
    // [read_file, read_file], [bash], [glob]
    expect(batches).toHaveLength(3);
    expect(batches[0]).toHaveLength(2);
    expect(batches[1]).toHaveLength(1);
    expect(batches[2]).toHaveLength(1);
  });

  it('batches conditionally-parallel tools targeting different files', () => {
    const tools = [
      { name: 'edit_file', id: '1', args: { path: '/a.ts' } },
      { name: 'edit_file', id: '2', args: { path: '/b.ts' } },
    ];
    const batches = groupToolCallsIntoBatches(tools);
    // Both target different files, so they should be in one batch
    expect(batches).toHaveLength(1);
    expect(batches[0]).toHaveLength(2);
  });

  it('splits conditionally-parallel tools with file conflicts', () => {
    const tools = [
      { name: 'edit_file', id: '1', args: { path: '/a.ts' } },
      { name: 'edit_file', id: '2', args: { path: '/a.ts' } },
    ];
    const batches = groupToolCallsIntoBatches(tools);
    // Same file → separate batches
    expect(batches).toHaveLength(2);
  });

  it('supports custom predicates', () => {
    const tools = [
      { name: 'custom_tool', id: '1' },
      { name: 'custom_tool', id: '2' },
    ];
    const batches = groupToolCallsIntoBatches(
      tools,
      () => true,  // all parallelizable
      () => false,
    );
    expect(batches).toHaveLength(1);
    expect(batches[0]).toHaveLength(2);
  });

  it('sequential tools flush accumulated parallel batch', () => {
    const tools = [
      { name: 'read_file', id: '1' },
      { name: 'glob', id: '2' },
      { name: 'bash', id: '3' },
    ];
    const batches = groupToolCallsIntoBatches(tools);
    expect(batches).toHaveLength(2);
    expect(batches[0]).toHaveLength(2); // read_file + glob
    expect(batches[1]).toHaveLength(1); // bash
  });
});

// =============================================================================
// extractToolFilePath
// =============================================================================

describe('extractToolFilePath', () => {
  it('extracts path from top-level "path" key', () => {
    expect(extractToolFilePath({ name: 'read_file', path: '/foo/bar.ts' })).toBe('/foo/bar.ts');
  });

  it('extracts path from top-level "file_path" key', () => {
    expect(extractToolFilePath({ name: 'read_file', file_path: '/src/main.ts' })).toBe('/src/main.ts');
  });

  it('extracts path from nested args object', () => {
    expect(extractToolFilePath({
      name: 'read_file',
      args: { path: '/nested/path.ts' },
    })).toBe('/nested/path.ts');
  });

  it('extracts path from nested input object', () => {
    expect(extractToolFilePath({
      name: 'read_file',
      input: { file_path: '/input/path.ts' },
    })).toBe('/input/path.ts');
  });

  it('returns null for tools without file paths', () => {
    expect(extractToolFilePath({ name: 'bash', command: 'ls' })).toBeNull();
  });

  it('returns null for empty tool call', () => {
    expect(extractToolFilePath({ name: 'unknown' })).toBeNull();
  });
});

// =============================================================================
// summarizeToolResult
// =============================================================================

describe('summarizeToolResult', () => {
  it('returns "No output" for null/undefined', () => {
    expect(summarizeToolResult('bash', null)).toBe('No output');
    expect(summarizeToolResult('bash', undefined)).toBe('No output');
  });

  it('summarizes list_files results', () => {
    const result = 'file1.ts\nfile2.ts\nfile3.ts';
    expect(summarizeToolResult('list_files', result)).toBe('Found 3 files');
  });

  it('summarizes glob results with singular', () => {
    expect(summarizeToolResult('glob', 'file1.ts')).toBe('Found 1 file');
  });

  it('summarizes bash success', () => {
    expect(summarizeToolResult('bash', 'done')).toBe('Success');
  });

  it('summarizes bash failure', () => {
    const result = 'Error: command failed\nexit code: 1';
    expect(summarizeToolResult('bash', result)).toContain('Failed');
  });

  it('summarizes read_file result', () => {
    const result = 'line1\nline2\nline3';
    expect(summarizeToolResult('read_file', result)).toBe('Read 3 lines');
  });

  it('summarizes write_file result', () => {
    expect(summarizeToolResult('write_file', 'ok')).toBe('File updated');
  });

  it('truncates long string results', () => {
    const longResult = 'x'.repeat(100);
    const summary = summarizeToolResult('some_tool', longResult);
    expect(summary.length).toBeLessThanOrEqual(50);
    expect(summary).toContain('...');
  });

  it('returns short results as-is', () => {
    expect(summarizeToolResult('custom', 'short')).toBe('short');
  });

  it('handles object results via JSON.stringify', () => {
    const result = { success: true, count: 5 };
    const summary = summarizeToolResult('custom', result);
    expect(summary).toContain('success');
  });
});

// =============================================================================
// formatToolArgsForPlan
// =============================================================================

describe('formatToolArgsForPlan', () => {
  it('formats write_file with path and content preview', () => {
    const result = formatToolArgsForPlan('write_file', {
      path: '/src/main.ts',
      content: 'console.log("hello");\n'.repeat(20),
    });
    expect(result).toContain('File: /src/main.ts');
    expect(result).toContain('Content preview:');
  });

  it('formats edit_file with path and old/new text', () => {
    const result = formatToolArgsForPlan('edit_file', {
      path: '/src/main.ts',
      old_string: 'old code',
      new_string: 'new code',
    });
    expect(result).toContain('File: /src/main.ts');
    expect(result).toContain('Old:');
    expect(result).toContain('New:');
  });

  it('formats bash with command', () => {
    const result = formatToolArgsForPlan('bash', { command: 'npm test' });
    expect(result).toContain('Command: npm test');
  });

  it('formats delete_file', () => {
    const result = formatToolArgsForPlan('delete_file', { path: '/tmp/file.ts' });
    expect(result).toContain('Delete: /tmp/file.ts');
  });

  it('formats spawn_agent with task', () => {
    const result = formatToolArgsForPlan('spawn_agent', {
      task: 'Investigate the auth module',
    });
    expect(result).toContain('Investigate the auth module');
  });

  it('formats unknown tools with JSON args', () => {
    const result = formatToolArgsForPlan('unknown_tool', { key: 'value' });
    expect(result).toContain('Args:');
    expect(result).toContain('key');
  });
});

// =============================================================================
// extractChangeReasoning
// =============================================================================

describe('extractChangeReasoning', () => {
  it('returns default message when no assistant messages', () => {
    const result = extractChangeReasoning(
      { name: 'write_file', arguments: { path: '/foo.ts' } },
      [],
    );
    expect(result).toContain('Proposed change: write_file');
  });

  it('extracts reasoning from spawn_agent task', () => {
    const messages: Message[] = [
      { role: 'assistant', content: 'Something before' },
    ];
    const result = extractChangeReasoning(
      { name: 'spawn_agent', arguments: { task: 'Investigate the auth system and report findings.' } },
      messages,
    );
    expect(result).toContain('Investigate the auth system');
  });

  it('extracts reasoning from assistant message about the file', () => {
    const messages: Message[] = [
      { role: 'assistant', content: 'I need to update main.ts to fix the import path.' },
    ];
    const result = extractChangeReasoning(
      { name: 'edit_file', arguments: { path: '/src/main.ts' } },
      messages,
    );
    expect(result).toContain('main.ts');
  });

  it('falls back to first paragraph', () => {
    const messages: Message[] = [
      { role: 'assistant', content: 'This is the first paragraph of explanation.\n\nSecond paragraph here.' },
    ];
    const result = extractChangeReasoning(
      { name: 'write_file', arguments: { path: '/src/unrelated.ts' } },
      messages,
    );
    expect(result).toContain('first paragraph');
  });

  it('truncates long reasoning at 500 chars', () => {
    const longContent = 'A'.repeat(600) + '\n\n' + 'B'.repeat(100);
    const messages: Message[] = [
      { role: 'assistant', content: longContent },
    ];
    const result = extractChangeReasoning(
      { name: 'write_file', arguments: { path: '/foo.ts' } },
      messages,
    );
    expect(result.length).toBeLessThanOrEqual(503); // 500 + '...'
  });
});
