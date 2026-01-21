/**
 * Exercise Tests: Lesson 4 - Streaming Buffer
 *
 * Run with: npm run test:lesson:4:exercise
 */

import { describe, it, expect } from 'vitest';

// Import from answers for testing
import { LineBuffer, collectLines } from './exercises/answers/exercise-1.js';

describe('LineBuffer', () => {
  describe('basic functionality', () => {
    it('should emit complete lines', async () => {
      const buffer = new LineBuffer();

      buffer.push('Hello World\n');
      buffer.end();

      const lines = await collectLines(buffer);
      expect(lines).toEqual(['Hello World']);
    });

    it('should handle multiple lines in one chunk', async () => {
      const buffer = new LineBuffer();

      buffer.push('Line 1\nLine 2\nLine 3\n');
      buffer.end();

      const lines = await collectLines(buffer);
      expect(lines).toEqual(['Line 1', 'Line 2', 'Line 3']);
    });

    it('should buffer incomplete lines', async () => {
      const buffer = new LineBuffer();

      buffer.push('Hello ');
      buffer.push('World\n');
      buffer.end();

      const lines = await collectLines(buffer);
      expect(lines).toEqual(['Hello World']);
    });

    it('should emit remaining data on end()', async () => {
      const buffer = new LineBuffer();

      buffer.push('No newline at end');
      buffer.end();

      const lines = await collectLines(buffer);
      expect(lines).toEqual(['No newline at end']);
    });
  });

  describe('chunked input', () => {
    it('should handle chunks split mid-word', async () => {
      const buffer = new LineBuffer();

      buffer.push('Hel');
      buffer.push('lo ');
      buffer.push('Wor');
      buffer.push('ld\n');
      buffer.end();

      const lines = await collectLines(buffer);
      expect(lines).toEqual(['Hello World']);
    });

    it('should handle chunks split at newline', async () => {
      const buffer = new LineBuffer();

      buffer.push('Line 1');
      buffer.push('\n');
      buffer.push('Line 2\n');
      buffer.end();

      const lines = await collectLines(buffer);
      expect(lines).toEqual(['Line 1', 'Line 2']);
    });

    it('should handle multiple newlines in chunk', async () => {
      const buffer = new LineBuffer();

      buffer.push('A\nB\nC\n');
      buffer.end();

      const lines = await collectLines(buffer);
      expect(lines).toEqual(['A', 'B', 'C']);
    });
  });

  describe('edge cases', () => {
    it('should handle empty chunks', async () => {
      const buffer = new LineBuffer();

      buffer.push('');
      buffer.push('Hello');
      buffer.push('');
      buffer.push(' World\n');
      buffer.push('');
      buffer.end();

      const lines = await collectLines(buffer);
      expect(lines).toEqual(['Hello World']);
    });

    it('should handle empty lines', async () => {
      const buffer = new LineBuffer();

      buffer.push('Line 1\n\nLine 3\n');
      buffer.end();

      const lines = await collectLines(buffer);
      expect(lines).toEqual(['Line 1', '', 'Line 3']);
    });

    it('should handle immediate end()', async () => {
      const buffer = new LineBuffer();
      buffer.end();

      const lines = await collectLines(buffer);
      expect(lines).toEqual([]);
    });

    it('should handle only newlines', async () => {
      const buffer = new LineBuffer();

      buffer.push('\n\n\n');
      buffer.end();

      const lines = await collectLines(buffer);
      expect(lines).toEqual(['', '', '']);
    });
  });

  describe('async iteration', () => {
    it('should yield lines as they become available', async () => {
      const buffer = new LineBuffer();
      const received: string[] = [];

      // Start consuming in background
      const consumer = (async () => {
        for await (const line of buffer) {
          received.push(line);
        }
      })();

      // Push data with delays
      buffer.push('First\n');
      await new Promise(r => setTimeout(r, 10));

      buffer.push('Second\n');
      await new Promise(r => setTimeout(r, 10));

      buffer.end();
      await consumer;

      expect(received).toEqual(['First', 'Second']);
    });

    it('should implement AsyncIterable interface', () => {
      const buffer = new LineBuffer();
      expect(typeof buffer[Symbol.asyncIterator]).toBe('function');
    });
  });
});

describe('collectLines helper', () => {
  it('should collect all lines into array', async () => {
    const buffer = new LineBuffer();
    buffer.push('A\nB\nC\n');
    buffer.end();

    const lines = await collectLines(buffer);
    expect(lines).toEqual(['A', 'B', 'C']);
  });

  it('should work with any AsyncIterable', async () => {
    async function* generator() {
      yield 'one';
      yield 'two';
      yield 'three';
    }

    const lines = await collectLines(generator());
    expect(lines).toEqual(['one', 'two', 'three']);
  });
});
