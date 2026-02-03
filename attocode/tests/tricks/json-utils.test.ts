/**
 * JSON Utilities Tests
 *
 * Tests for robust JSON parsing with multi-level fallback and recovery.
 */

import { describe, it, expect } from 'vitest';
import {
  extractJsonObject,
  extractAllJsonObjects,
  safeParseJson,
  extractToolCallJson,
  extractAllToolCalls,
} from '../../src/tricks/json-utils.js';

describe('extractJsonObject', () => {
  describe('basic extraction', () => {
    it('should extract a simple JSON object', () => {
      const result = extractJsonObject('{"a": 1}');
      expect(result).toEqual({ json: '{"a": 1}', endIndex: 8 });
    });

    it('should extract JSON from surrounding text', () => {
      const result = extractJsonObject('Here is the result: {"key": "value"} and more text');
      expect(result?.json).toBe('{"key": "value"}');
    });

    it('should return null when no JSON found', () => {
      const result = extractJsonObject('no json here');
      expect(result).toBeNull();
    });

    it('should start from specified position', () => {
      const text = '{"first": 1} {"second": 2}';
      const result = extractJsonObject(text, 13);
      expect(result?.json).toBe('{"second": 2}');
    });
  });

  describe('nested objects', () => {
    it('should handle nested objects', () => {
      const json = '{"outer": {"inner": {"deep": 1}}}';
      const result = extractJsonObject(json);
      expect(result?.json).toBe(json);
    });

    it('should handle nested arrays', () => {
      const json = '{"arr": [1, [2, [3]]]}';
      const result = extractJsonObject(json);
      expect(result?.json).toBe(json);
    });

    it('should handle mixed nesting', () => {
      const json = '{"a": {"b": [1, {"c": 2}]}}';
      const result = extractJsonObject(json);
      expect(result?.json).toBe(json);
    });
  });

  describe('string handling', () => {
    it('should handle strings containing braces', () => {
      const json = '{"text": "hello { } world"}';
      const result = extractJsonObject(json);
      expect(result?.json).toBe(json);
    });

    it('should handle escaped quotes in strings', () => {
      const json = '{"text": "he said \\"hi\\""}';
      const result = extractJsonObject(json);
      expect(result?.json).toBe(json);
    });

    it('should handle strings with backslashes', () => {
      const json = '{"path": "C:\\\\Users\\\\name"}';
      const result = extractJsonObject(json);
      expect(result?.json).toBe(json);
    });
  });

  describe('incomplete JSON', () => {
    it('should return null for unclosed objects', () => {
      const result = extractJsonObject('{"a": 1');
      expect(result).toBeNull();
    });

    it('should return null for unclosed strings', () => {
      const result = extractJsonObject('{"a": "incomplete');
      expect(result).toBeNull();
    });
  });
});

describe('extractAllJsonObjects', () => {
  it('should extract multiple JSON objects', () => {
    const text = '{"a": 1} some text {"b": 2} more text {"c": 3}';
    const results = extractAllJsonObjects(text);
    expect(results).toEqual(['{"a": 1}', '{"b": 2}', '{"c": 3}']);
  });

  it('should return empty array when no JSON found', () => {
    const results = extractAllJsonObjects('no json here');
    expect(results).toEqual([]);
  });

  it('should handle adjacent JSON objects', () => {
    const text = '{"a": 1}{"b": 2}';
    const results = extractAllJsonObjects(text);
    expect(results).toEqual(['{"a": 1}', '{"b": 2}']);
  });
});

describe('safeParseJson', () => {
  describe('Level 1: direct parse', () => {
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

    it('should handle whitespace', () => {
      const result = safeParseJson('  {"key": "value"}  ');
      expect(result.success).toBe(true);
    });
  });

  describe('Level 2: extraction', () => {
    it('should extract JSON from text', () => {
      const result = safeParseJson('The result is {"key": "value"} as expected');
      expect(result.success).toBe(true);
      expect(result.value).toEqual({ key: 'value' });
    });

    it('should extract from code blocks', () => {
      const result = safeParseJson('```json\n{"key": "value"}\n```');
      expect(result.success).toBe(true);
    });
  });

  describe('Level 3: recovery', () => {
    it('should fix trailing commas', () => {
      const result = safeParseJson('{"a": 1,}');
      expect(result.success).toBe(true);
      expect(result.value).toEqual({ a: 1 });
      expect(result.recovered).toBe(true);
    });

    it('should fix single quotes', () => {
      const result = safeParseJson("{'a': 1}");
      expect(result.success).toBe(true);
      expect(result.value).toEqual({ a: 1 });
      expect(result.recovered).toBe(true);
    });

    it('should fix unquoted keys', () => {
      const result = safeParseJson('{foo: 1}');
      expect(result.success).toBe(true);
      expect(result.value).toEqual({ foo: 1 });
      expect(result.recovered).toBe(true);
    });

    it('should skip recovery when disabled', () => {
      const result = safeParseJson('{"a": 1,}', { attemptRecovery: false });
      // Without recovery, this might still work due to extraction
      // Let's test with something that definitely needs recovery
      const result2 = safeParseJson('{foo: 1}', { attemptRecovery: false });
      expect(result2.success).toBe(false);
    });
  });

  describe('error handling', () => {
    it('should return error for null input', () => {
      const result = safeParseJson(null as unknown as string);
      expect(result.success).toBe(false);
      expect(result.error).toContain('Invalid input');
    });

    it('should return error for non-string input', () => {
      const result = safeParseJson(123 as unknown as string);
      expect(result.success).toBe(false);
    });

    it('should include context in error message', () => {
      const result = safeParseJson('invalid', { context: 'test operation' });
      expect(result.success).toBe(false);
      expect(result.error).toContain('test operation');
    });

    it('should return error for unrecoverable input', () => {
      const result = safeParseJson('completely invalid content with no JSON');
      expect(result.success).toBe(false);
    });
  });

  describe('type inference', () => {
    it('should preserve type information', () => {
      interface TestType {
        name: string;
        count: number;
      }

      const result = safeParseJson<TestType>('{"name": "test", "count": 5}');
      expect(result.success).toBe(true);

      if (result.success && result.value) {
        // TypeScript should know these properties exist
        expect(result.value.name).toBe('test');
        expect(result.value.count).toBe(5);
      }
    });
  });
});

describe('extractToolCallJson', () => {
  describe('code block format', () => {
    it('should extract from json code block', () => {
      const response = `Here's the tool call:
\`\`\`json
{"tool": "read_file", "input": {"path": "/test.txt"}}
\`\`\``;

      const result = extractToolCallJson(response);
      expect(result).toEqual({
        tool: 'read_file',
        input: { path: '/test.txt' },
      });
    });

    it('should extract from plain code block', () => {
      const response = `\`\`\`
{"tool": "write_file", "input": {"path": "test.txt", "content": "hello"}}
\`\`\``;

      const result = extractToolCallJson(response);
      expect(result).toEqual({
        tool: 'write_file',
        input: { path: 'test.txt', content: 'hello' },
      });
    });
  });

  describe('inline format', () => {
    it('should extract inline JSON', () => {
      const response = 'I need to call {"tool": "search", "input": {"query": "test"}}';

      const result = extractToolCallJson(response);
      expect(result).toEqual({
        tool: 'search',
        input: { query: 'test' },
      });
    });
  });

  describe('nested inputs', () => {
    it('should handle nested input objects', () => {
      const response = '{"tool": "api", "input": {"data": {"nested": {"deep": 1}}}}';

      const result = extractToolCallJson(response);
      expect(result).toEqual({
        tool: 'api',
        input: { data: { nested: { deep: 1 } } },
      });
    });
  });

  describe('missing input', () => {
    it('should handle missing input field', () => {
      const response = '{"tool": "no_args"}';

      const result = extractToolCallJson(response);
      expect(result).toEqual({
        tool: 'no_args',
        input: {},
      });
    });
  });

  describe('invalid tool calls', () => {
    it('should return null for missing tool field', () => {
      const response = '{"input": {"path": "test.txt"}}';
      const result = extractToolCallJson(response);
      expect(result).toBeNull();
    });

    it('should return null for non-string tool', () => {
      const response = '{"tool": 123, "input": {}}';
      const result = extractToolCallJson(response);
      expect(result).toBeNull();
    });

    it('should return null when no JSON found', () => {
      const response = 'No tool calls here, just text.';
      const result = extractToolCallJson(response);
      expect(result).toBeNull();
    });
  });
});

describe('extractAllToolCalls', () => {
  it('should extract multiple tool calls from code blocks', () => {
    const response = `
First action:
\`\`\`json
{"tool": "read_file", "input": {"path": "a.txt"}}
\`\`\`

Second action:
\`\`\`json
{"tool": "write_file", "input": {"path": "b.txt", "content": "data"}}
\`\`\`
`;

    const results = extractAllToolCalls(response);
    expect(results).toHaveLength(2);
    expect(results[0].tool).toBe('read_file');
    expect(results[1].tool).toBe('write_file');
  });

  it('should extract from inline JSON when no code blocks', () => {
    const response = `Calling {"tool": "a", "input": {}} and {"tool": "b", "input": {}}`;

    const results = extractAllToolCalls(response);
    expect(results).toHaveLength(2);
    expect(results[0].tool).toBe('a');
    expect(results[1].tool).toBe('b');
  });

  it('should return empty array when no tool calls found', () => {
    const results = extractAllToolCalls('Just regular text without any tool calls.');
    expect(results).toEqual([]);
  });

  it('should skip invalid tool call objects', () => {
    const response = `
\`\`\`json
{"notATool": "value"}
\`\`\`
\`\`\`json
{"tool": "valid", "input": {}}
\`\`\`
`;

    const results = extractAllToolCalls(response);
    expect(results).toHaveLength(1);
    expect(results[0].tool).toBe('valid');
  });
});
