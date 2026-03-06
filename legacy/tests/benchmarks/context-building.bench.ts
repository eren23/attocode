/**
 * Context Building Performance Benchmarks
 *
 * Measures performance of context-related operations.
 */

import { bench, describe } from 'vitest';
import { safeParseJson, extractJsonObject, extractAllJsonObjects } from '../../src/tricks/json-utils.js';

// =============================================================================
// TEST DATA GENERATORS
// =============================================================================

function generateMessages(count: number): Array<{ role: string; content: string }> {
  return Array.from({ length: count }, (_, i) => ({
    role: i % 2 === 0 ? 'user' : 'assistant',
    content: `Message ${i}: ${'Lorem ipsum dolor sit amet. '.repeat(10)}`,
  }));
}

function generateNestedJson(depth: number): string {
  if (depth === 0) return '{"value": 1}';
  return `{"nested": ${generateNestedJson(depth - 1)}}`;
}

function generateJsonWithStrings(count: number): string {
  const fields = Array.from({ length: count }, (_, i) =>
    `"field${i}": "value with {braces} and \\"quotes\\" ${i}"`
  );
  return `{${fields.join(', ')}}`;
}

// =============================================================================
// JSON PARSING BENCHMARKS
// =============================================================================

describe('JSON Parsing Performance', () => {
  const simpleJson = '{"name": "test", "value": 123}';
  const nestedJson = generateNestedJson(10);
  const largeJson = generateJsonWithStrings(100);
  const jsonInText = `Here is the result: ${simpleJson} and more text follows.`;

  bench('safeParseJson - simple object', () => {
    safeParseJson(simpleJson);
  });

  bench('safeParseJson - deeply nested (10 levels)', () => {
    safeParseJson(nestedJson);
  });

  bench('safeParseJson - large object (100 fields)', () => {
    safeParseJson(largeJson);
  });

  bench('safeParseJson - extraction from text', () => {
    safeParseJson(jsonInText);
  });

  bench('extractJsonObject - simple', () => {
    extractJsonObject(simpleJson);
  });

  bench('extractJsonObject - nested', () => {
    extractJsonObject(nestedJson);
  });

  bench('extractJsonObject - with string escapes', () => {
    extractJsonObject(largeJson);
  });
});

describe('JSON Extraction Performance', () => {
  const multipleObjects = Array(10)
    .fill(null)
    .map((_, i) => `{"id": ${i}}`)
    .join(' text between ');

  const manyObjects = Array(100)
    .fill(null)
    .map((_, i) => `{"id": ${i}}`)
    .join(' ');

  bench('extractAllJsonObjects - 10 objects', () => {
    extractAllJsonObjects(multipleObjects);
  });

  bench('extractAllJsonObjects - 100 objects', () => {
    extractAllJsonObjects(manyObjects);
  });
});

// =============================================================================
// MESSAGE PROCESSING BENCHMARKS
// =============================================================================

describe('Message Processing Performance', () => {
  const messages10 = generateMessages(10);
  const messages100 = generateMessages(100);
  const messages1000 = generateMessages(1000);

  bench('process 10 messages', () => {
    // Simulate context building
    const context = messages10.map(m => `${m.role}: ${m.content}`).join('\n');
    // Simulate token counting (simple approximation)
    context.split(/\s+/).length;
  });

  bench('process 100 messages', () => {
    const context = messages100.map(m => `${m.role}: ${m.content}`).join('\n');
    context.split(/\s+/).length;
  });

  bench('process 1000 messages', () => {
    const context = messages1000.map(m => `${m.role}: ${m.content}`).join('\n');
    context.split(/\s+/).length;
  });
});

// =============================================================================
// STRING OPERATIONS BENCHMARKS
// =============================================================================

describe('String Operations Performance', () => {
  const longString = 'x'.repeat(100000);
  const searchTarget = 'needle';
  const stringWithNeedle = longString.slice(0, 50000) + searchTarget + longString.slice(50000);

  bench('string search in 100KB', () => {
    stringWithNeedle.includes(searchTarget);
  });

  bench('string split 100KB', () => {
    longString.split('\n');
  });

  bench('string slice 100KB', () => {
    longString.slice(0, 50000);
  });

  bench('regex match in 100KB', () => {
    stringWithNeedle.match(/needle/);
  });
});
