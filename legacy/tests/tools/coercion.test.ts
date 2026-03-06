/**
 * Unit tests for coerceBoolean() from src/tools/coercion.ts.
 *
 * Weaker models sometimes send booleans as strings. coerceBoolean() uses
 * z.preprocess() to handle this before Zod validation.
 */

import { describe, it, expect } from 'vitest';
import { coerceBoolean, coerceString } from '../../src/tools/coercion.js';

describe('coerceBoolean', () => {
  const schema = coerceBoolean();

  describe('actual booleans pass through', () => {
    it('should accept true', () => {
      expect(schema.parse(true)).toBe(true);
    });

    it('should accept false', () => {
      expect(schema.parse(false)).toBe(false);
    });
  });

  describe('string "true"/"false" coerce to booleans', () => {
    it('should coerce "true" to true', () => {
      expect(schema.parse('true')).toBe(true);
    });

    it('should coerce "false" to false', () => {
      expect(schema.parse('false')).toBe(false);
    });
  });

  describe('case-insensitive and whitespace-tolerant', () => {
    it('should coerce "TRUE" to true', () => {
      expect(schema.parse('TRUE')).toBe(true);
    });

    it('should coerce "FALSE" to false', () => {
      expect(schema.parse('FALSE')).toBe(false);
    });

    it('should coerce "True" to true', () => {
      expect(schema.parse('True')).toBe(true);
    });

    it('should coerce " True " (with whitespace) to true', () => {
      expect(schema.parse(' True ')).toBe(true);
    });

    it('should coerce " false " (with whitespace) to false', () => {
      expect(schema.parse(' false ')).toBe(false);
    });
  });

  describe('"1"/"0" and "yes"/"no" coerce correctly', () => {
    it('should coerce "1" to true', () => {
      expect(schema.parse('1')).toBe(true);
    });

    it('should coerce "0" to false', () => {
      expect(schema.parse('0')).toBe(false);
    });

    it('should coerce "yes" to true', () => {
      expect(schema.parse('yes')).toBe(true);
    });

    it('should coerce "no" to false', () => {
      expect(schema.parse('no')).toBe(false);
    });

    it('should coerce "YES" to true', () => {
      expect(schema.parse('YES')).toBe(true);
    });

    it('should coerce "NO" to false', () => {
      expect(schema.parse('NO')).toBe(false);
    });
  });

  describe('non-boolean strings fail validation', () => {
    it('should reject "maybe"', () => {
      expect(() => schema.parse('maybe')).toThrow();
    });

    it('should reject "2"', () => {
      expect(() => schema.parse('2')).toThrow();
    });

    it('should reject empty string', () => {
      expect(() => schema.parse('')).toThrow();
    });
  });

  describe('non-string, non-boolean values fail validation', () => {
    it('should reject number 1 (passes through to z.boolean which rejects)', () => {
      expect(() => schema.parse(1)).toThrow();
    });

    it('should reject number 0', () => {
      expect(() => schema.parse(0)).toThrow();
    });

    it('should reject null', () => {
      expect(() => schema.parse(null)).toThrow();
    });

    it('should reject undefined', () => {
      expect(() => schema.parse(undefined)).toThrow();
    });

    it('should reject object', () => {
      expect(() => schema.parse({})).toThrow();
    });
  });
});

describe('coerceString', () => {
  const schema = coerceString();

  it('passes strings through unchanged', () => {
    expect(schema.parse('hello world')).toBe('hello world');
  });

  it('joins string arrays with newlines', () => {
    expect(schema.parse(['line1', 'line2', 'line3'])).toBe('line1\nline2\nline3');
  });

  it('coerces mixed-type arrays to string', () => {
    expect(schema.parse(['text', 42, true])).toBe('text\n42\ntrue');
  });

  it('coerces empty array to empty string', () => {
    expect(schema.parse([])).toBe('');
  });

  it('rejects non-string non-array values', () => {
    expect(() => schema.parse(123)).toThrow();
    expect(() => schema.parse(null)).toThrow();
    expect(() => schema.parse(undefined)).toThrow();
  });
});
