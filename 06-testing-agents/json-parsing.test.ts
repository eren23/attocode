/**
 * Lesson 6: JSON Parsing Tests
 *
 * Tests for the json-utils module, verifying robust JSON extraction
 * that handles nested objects (the broken regex problem).
 */

import { describe, it, expect } from 'vitest';
import {
  extractJsonObject,
  extractAllJsonObjects,
  safeParseJson,
  extractToolCallJson,
  extractAllToolCalls,
} from '../tricks/json-utils.js';

// =============================================================================
// EXTRACT JSON OBJECT TESTS
// =============================================================================

describe('extractJsonObject', () => {
  describe('simple objects', () => {
    it('should extract a simple JSON object', () => {
      const result = extractJsonObject('{"key": "value"}');
      expect(result).toEqual({
        json: '{"key": "value"}',
        endIndex: 16,
      });
    });

    it('should extract JSON from surrounding text', () => {
      const result = extractJsonObject('Here is the data: {"name": "test"} and more text');
      expect(result?.json).toBe('{"name": "test"}');
    });

    it('should handle empty objects', () => {
      const result = extractJsonObject('{}');
      expect(result?.json).toBe('{}');
    });
  });

  describe('nested objects (the failing case)', () => {
    it('should extract deeply nested objects', () => {
      const input = '{"tool": "x", "input": {"nested": "value"}}';
      const result = extractJsonObject(input);
      expect(result?.json).toBe(input);
    });

    it('should handle multiple levels of nesting', () => {
      const input = '{"a": {"b": {"c": {"d": 1}}}}';
      const result = extractJsonObject(input);
      expect(result?.json).toBe(input);
      expect(JSON.parse(result!.json)).toEqual({ a: { b: { c: { d: 1 } } } });
    });

    it('should handle real-world tool call with nested input', () => {
      const input = '```json\n{"tool": "read_file", "input": {"path": "/home/user/file.txt", "options": {"encoding": "utf-8"}}}\n```';
      const result = extractJsonObject(input);
      expect(result?.json).toBe('{"tool": "read_file", "input": {"path": "/home/user/file.txt", "options": {"encoding": "utf-8"}}}');
    });
  });

  describe('nested arrays', () => {
    it('should handle arrays inside objects', () => {
      const input = '{"items": [1, 2, 3]}';
      const result = extractJsonObject(input);
      expect(result?.json).toBe(input);
    });

    it('should handle nested arrays', () => {
      const input = '{"matrix": [[1, 2], [3, 4]]}';
      const result = extractJsonObject(input);
      expect(result?.json).toBe(input);
    });

    it('should handle objects inside arrays', () => {
      const input = '{"users": [{"name": "Alice"}, {"name": "Bob"}]}';
      const result = extractJsonObject(input);
      expect(result?.json).toBe(input);
    });
  });

  describe('strings containing braces', () => {
    it('should ignore braces inside strings', () => {
      const input = '{"text": "hello { } world"}';
      const result = extractJsonObject(input);
      expect(result?.json).toBe(input);
      expect(JSON.parse(result!.json)).toEqual({ text: 'hello { } world' });
    });

    it('should handle JSON-like content inside strings', () => {
      const input = '{"message": "The format is {key: value}"}';
      const result = extractJsonObject(input);
      expect(result?.json).toBe(input);
    });

    it('should handle deeply nested braces in strings', () => {
      const input = '{"code": "function() { if (x) { return {a: 1}; } }"}';
      const result = extractJsonObject(input);
      expect(result?.json).toBe(input);
    });
  });

  describe('escaped quotes', () => {
    it('should handle escaped quotes in strings', () => {
      const input = '{"text": "he said \\"hi\\""}';
      const result = extractJsonObject(input);
      expect(result?.json).toBe(input);
      expect(JSON.parse(result!.json)).toEqual({ text: 'he said "hi"' });
    });

    it('should handle multiple escaped quotes', () => {
      const input = '{"quote": "\\"Hello,\\" she said, \\"how are you?\\""}';
      const result = extractJsonObject(input);
      expect(result?.json).toBe(input);
    });

    it('should handle escaped backslashes', () => {
      const input = '{"path": "C:\\\\Users\\\\test"}';
      const result = extractJsonObject(input);
      expect(result?.json).toBe(input);
      expect(JSON.parse(result!.json)).toEqual({ path: 'C:\\Users\\test' });
    });
  });

  describe('edge cases', () => {
    it('should return null for empty string', () => {
      expect(extractJsonObject('')).toBeNull();
    });

    it('should return null for text without JSON', () => {
      expect(extractJsonObject('Hello, world!')).toBeNull();
    });

    it('should return null for incomplete JSON', () => {
      expect(extractJsonObject('{"incomplete": ')).toBeNull();
    });

    it('should return null for unclosed braces', () => {
      expect(extractJsonObject('{"a": {"b": 1}')).toBeNull();
    });

    it('should extract first object when multiple exist', () => {
      const result = extractJsonObject('{"first": 1} {"second": 2}');
      expect(result?.json).toBe('{"first": 1}');
      expect(result?.endIndex).toBe(12);
    });
  });
});

// =============================================================================
// EXTRACT ALL JSON OBJECTS TESTS
// =============================================================================

describe('extractAllJsonObjects', () => {
  it('should extract multiple JSON objects', () => {
    const input = '{"a": 1} some text {"b": 2} more {"c": 3}';
    const results = extractAllJsonObjects(input);
    expect(results).toEqual(['{"a": 1}', '{"b": 2}', '{"c": 3}']);
  });

  it('should return empty array for no JSON', () => {
    expect(extractAllJsonObjects('no json here')).toEqual([]);
  });
});

// =============================================================================
// SAFE PARSE JSON TESTS
// =============================================================================

describe('safeParseJson', () => {
  describe('valid JSON', () => {
    it('should parse valid JSON directly', () => {
      const result = safeParseJson('{"key": "value"}');
      expect(result.success).toBe(true);
      expect(result.value).toEqual({ key: 'value' });
    });

    it('should parse arrays', () => {
      const result = safeParseJson('[1, 2, 3]');
      expect(result.success).toBe(true);
      expect(result.value).toEqual([1, 2, 3]);
    });

    it('should parse primitives', () => {
      expect(safeParseJson('"hello"').value).toBe('hello');
      expect(safeParseJson('42').value).toBe(42);
      expect(safeParseJson('true').value).toBe(true);
      expect(safeParseJson('null').value).toBe(null);
    });
  });

  describe('JSON extraction from text', () => {
    it('should extract JSON from surrounding text', () => {
      const result = safeParseJson('The result is {"status": "ok"} done');
      expect(result.success).toBe(true);
      expect(result.value).toEqual({ status: 'ok' });
    });

    it('should handle whitespace', () => {
      const result = safeParseJson('  \n  {"key": "value"}  \n  ');
      expect(result.success).toBe(true);
      expect(result.value).toEqual({ key: 'value' });
    });
  });

  describe('malformed JSON recovery', () => {
    it('should recover from trailing commas', () => {
      const result = safeParseJson('{"a": 1,}');
      expect(result.success).toBe(true);
      expect(result.value).toEqual({ a: 1 });
      expect(result.recovered).toBe(true);
    });

    it('should recover from single quotes', () => {
      const result = safeParseJson("{'key': 'value'}");
      expect(result.success).toBe(true);
      expect(result.value).toEqual({ key: 'value' });
      expect(result.recovered).toBe(true);
    });

    it('should not attempt recovery when disabled', () => {
      const result = safeParseJson('{"a": 1,}', { attemptRecovery: false });
      expect(result.success).toBe(false);
    });
  });

  describe('error handling', () => {
    it('should return error for invalid input', () => {
      const result = safeParseJson('not json at all');
      expect(result.success).toBe(false);
      expect(result.error).toContain('Failed to parse');
    });

    it('should include context in error message', () => {
      const result = safeParseJson('invalid', { context: 'tool read_file' });
      expect(result.error).toContain('tool read_file');
    });

    it('should handle empty string', () => {
      const result = safeParseJson('');
      expect(result.success).toBe(false);
    });

    it('should handle null/undefined gracefully', () => {
      expect(safeParseJson(null as any).success).toBe(false);
      expect(safeParseJson(undefined as any).success).toBe(false);
    });
  });
});

// =============================================================================
// EXTRACT TOOL CALL JSON TESTS
// =============================================================================

describe('extractToolCallJson', () => {
  describe('code block format', () => {
    it('should extract tool call from json code block', () => {
      const response = 'I\'ll read the file.\n```json\n{"tool": "read_file", "input": {"path": "test.txt"}}\n```';
      const result = extractToolCallJson(response);
      expect(result).toEqual({
        tool: 'read_file',
        input: { path: 'test.txt' },
      });
    });

    it('should extract from plain code block', () => {
      const response = '```\n{"tool": "bash", "input": {"command": "ls"}}\n```';
      const result = extractToolCallJson(response);
      expect(result).toEqual({
        tool: 'bash',
        input: { command: 'ls' },
      });
    });

    it('should handle nested input objects', () => {
      const response = '```json\n{"tool": "api_call", "input": {"endpoint": "/users", "params": {"id": 123, "include": ["profile", "settings"]}}}\n```';
      const result = extractToolCallJson(response);
      expect(result).toEqual({
        tool: 'api_call',
        input: {
          endpoint: '/users',
          params: { id: 123, include: ['profile', 'settings'] },
        },
      });
    });
  });

  describe('inline JSON format', () => {
    it('should extract inline tool call', () => {
      const response = 'Here\'s the tool call: {"tool": "search", "input": {"query": "test"}}';
      const result = extractToolCallJson(response);
      expect(result).toEqual({
        tool: 'search',
        input: { query: 'test' },
      });
    });
  });

  describe('edge cases', () => {
    it('should return null for response without tool call', () => {
      const response = 'Just a regular message without any tool calls.';
      expect(extractToolCallJson(response)).toBeNull();
    });

    it('should return null for JSON without tool property', () => {
      const response = '```json\n{"name": "test"}\n```';
      expect(extractToolCallJson(response)).toBeNull();
    });

    it('should handle missing input property', () => {
      const response = '```json\n{"tool": "simple"}\n```';
      const result = extractToolCallJson(response);
      expect(result).toEqual({
        tool: 'simple',
        input: {},
      });
    });

    it('should handle complex real-world response', () => {
      const response = `I'll help you with that. Let me read the file first.

\`\`\`json
{"tool": "read_file", "input": {"path": "/home/user/project/config.json", "encoding": "utf-8"}}
\`\`\`

After reading the file, I'll analyze its contents.`;

      const result = extractToolCallJson(response);
      expect(result).toEqual({
        tool: 'read_file',
        input: { path: '/home/user/project/config.json', encoding: 'utf-8' },
      });
    });
  });
});

// =============================================================================
// EXTRACT ALL TOOL CALLS TESTS
// =============================================================================

describe('extractAllToolCalls', () => {
  it('should extract multiple tool calls', () => {
    const response = `
\`\`\`json
{"tool": "list_files", "input": {"path": "."}}
\`\`\`

\`\`\`json
{"tool": "read_file", "input": {"path": "main.ts"}}
\`\`\`
`;
    const results = extractAllToolCalls(response);
    expect(results).toHaveLength(2);
    expect(results[0].tool).toBe('list_files');
    expect(results[1].tool).toBe('read_file');
  });

  it('should return empty array for no tool calls', () => {
    expect(extractAllToolCalls('No tools here')).toEqual([]);
  });
});
