/**
 * MCP Tool Validator Tests
 */

import { describe, it, expect } from 'vitest';
import {
  validateToolDescription,
  validateAllTools,
  formatValidationSummary,
  createToolValidator,
} from '../src/integrations/mcp-tool-validator.js';

describe('validateToolDescription', () => {
  it('should score well-documented tool highly', () => {
    const result = validateToolDescription({
      name: 'read_file',
      description: 'Read the contents of a file at the given path and return its text content.',
      inputSchema: {
        type: 'object',
        properties: { path: { type: 'string', description: 'Path to the file' } },
        required: ['path'],
      },
    });
    expect(result.score).toBeGreaterThanOrEqual(80);
    expect(result.issues).toHaveLength(0);
  });

  it('should penalize missing description', () => {
    const result = validateToolDescription({ name: 'tool' });
    expect(result.score).toBeLessThan(70);
    expect(result.issues.some(i => i.includes('No description'))).toBe(true);
  });

  it('should penalize short description', () => {
    const result = validateToolDescription({ name: 'tool', description: 'Does stuff' });
    expect(result.issues.some(i => i.includes('too short'))).toBe(true);
  });

  it('should penalize restated tool name', () => {
    const result = validateToolDescription({ name: 'read_file', description: 'Read file' });
    expect(result.issues.some(i => i.includes('restates'))).toBe(true);
  });

  it('should penalize undocumented properties', () => {
    const result = validateToolDescription({
      name: 'write_file',
      description: 'Write content to a file at the specified path.',
      inputSchema: {
        type: 'object',
        properties: {
          path: { type: 'string' },
          content: { type: 'string', description: 'Content to write' },
        },
      },
    });
    expect(result.issues.some(i => i.includes('missing descriptions'))).toBe(true);
  });

  it('should suggest required params when missing', () => {
    const result = validateToolDescription({
      name: 'search',
      description: 'Search for files matching a pattern in the codebase.',
      inputSchema: {
        type: 'object',
        properties: { query: { type: 'string', description: 'Query' } },
      },
    });
    expect(result.suggestions.some(s => s.includes('required'))).toBe(true);
  });

  it('should suggest examples when requireExamples is true', () => {
    const result = validateToolDescription(
      { name: 'tool', description: 'A useful tool that processes data.' },
      { requireExamples: true },
    );
    expect(result.suggestions.some(s => s.includes('example'))).toBe(true);
  });

  it('should clamp score to 0 minimum', () => {
    const result = validateToolDescription({ name: '' });
    expect(result.score).toBeGreaterThanOrEqual(0);
  });
});

describe('validateAllTools', () => {
  it('should sort by score ascending (worst first)', () => {
    const results = validateAllTools([
      { name: 'good', description: 'A tool that does something useful and important.' },
      { name: 'bad' },
    ]);
    expect(results[0].score).toBeLessThanOrEqual(results[1].score);
  });
});

describe('formatValidationSummary', () => {
  it('should show pass/fail counts', () => {
    const summary = formatValidationSummary([
      { toolName: 'good', score: 90, issues: [], suggestions: [] },
      { toolName: 'bad', score: 20, issues: ['No description'], suggestions: [] },
    ]);
    expect(summary).toContain('1/2 passed');
    expect(summary).toContain('bad');
  });

  it('should omit Failed section when all pass', () => {
    const summary = formatValidationSummary([
      { toolName: 'a', score: 80, issues: [], suggestions: [] },
    ]);
    expect(summary).toContain('1/1 passed');
    expect(summary).not.toContain('Failed');
  });
});

describe('createToolValidator', () => {
  it('should apply custom config', () => {
    const v = createToolValidator({ minDescriptionLength: 50 });
    const result = v.validate({ name: 'tool', description: 'Short desc here' });
    expect(result.issues.some(i => i.includes('too short'))).toBe(true);
  });
});
