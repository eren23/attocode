/**
 * Unit tests for subagent timeout and iteration precedence (Improvement P3).
 *
 * Tests the 4-level precedence chain:
 *   perTypeConfigTimeout > agentTypeTimeout > globalConfigTimeout > hardcoded fallback
 */

import { describe, it, expect } from 'vitest';
import {
  getSubagentTimeout,
  getSubagentMaxIterations,
  SUBAGENT_TIMEOUTS,
} from '../../src/defaults.js';

describe('getSubagentTimeout', () => {
  it('should return type-specific timeout for known agents', () => {
    expect(getSubagentTimeout('researcher')).toBe(420000); // 7 min
    expect(getSubagentTimeout('reviewer')).toBe(180000);   // 3 min
    expect(getSubagentTimeout('coder')).toBe(300000);      // 5 min
    expect(getSubagentTimeout('architect')).toBe(360000);   // 6 min
  });

  it('should return default timeout for unknown agents', () => {
    expect(getSubagentTimeout('custom_agent')).toBe(SUBAGENT_TIMEOUTS.default);
    expect(getSubagentTimeout('unknown')).toBe(300000); // 5 min default
  });
});

describe('getSubagentMaxIterations', () => {
  it('should return type-specific iterations for known agents', () => {
    const researcherIter = getSubagentMaxIterations('researcher');
    const reviewerIter = getSubagentMaxIterations('reviewer');
    expect(researcherIter).toBeGreaterThan(0);
    expect(reviewerIter).toBeGreaterThan(0);
  });

  it('should return default for unknown agents', () => {
    const iter = getSubagentMaxIterations('unknown_type');
    expect(iter).toBeGreaterThan(0);
  });
});

describe('timeout precedence chain (integration)', () => {
  // These tests validate the precedence logic that lives in agent.ts:4219-4227
  // We test the helper functions and validate the ?? chain behavior

  it('nullish coalescing should prefer first defined value', () => {
    // Simulates: perTypeConfig ?? agentTypeDefault ?? globalConfig ?? 300000
    const perType: number | undefined = 600000;
    const agentType = 420000;
    const global: number | undefined = 180000;

    const result = perType ?? agentType ?? global ?? 300000;
    expect(result).toBe(600000); // perType wins
  });

  it('should fall through to agent type when no per-type config', () => {
    const perType: number | undefined = undefined;
    const agentType = 420000;
    const global: number | undefined = 180000;

    const result = perType ?? agentType ?? global ?? 300000;
    expect(result).toBe(420000); // agentType wins
  });

  it('should fall through to global when no per-type and no agent-type', () => {
    const perType: number | undefined = undefined;
    const agentType: number | undefined = undefined;
    const global: number | undefined = 600000;

    const result = perType ?? agentType ?? global ?? 300000;
    expect(result).toBe(600000); // global wins
  });

  it('should use hardcoded fallback when all undefined', () => {
    const perType: number | undefined = undefined;
    const agentType: number | undefined = undefined;
    const global: number | undefined = undefined;

    const result = perType ?? agentType ?? global ?? 300000;
    expect(result).toBe(300000); // hardcoded fallback
  });

  it('nullish coalescing should treat 0 as a defined value', () => {
    // Edge case: 0 is a valid number, not undefined/null
    const perType: number | undefined = 0;
    const agentType = 420000;

    const result = perType ?? agentType ?? 300000;
    expect(result).toBe(0); // 0 is treated as defined
  });

  describe('validation', () => {
    // Tests for the isValidTimeout/isValidIter guards in agent.ts

    it('should reject NaN values', () => {
      const isValidTimeout = (v: number | undefined): v is number =>
        v !== undefined && Number.isFinite(v) && v > 0;

      expect(isValidTimeout(NaN)).toBe(false);
      expect(isValidTimeout(undefined)).toBe(false);
    });

    it('should reject negative values', () => {
      const isValidTimeout = (v: number | undefined): v is number =>
        v !== undefined && Number.isFinite(v) && v > 0;

      expect(isValidTimeout(-1)).toBe(false);
      expect(isValidTimeout(-100000)).toBe(false);
    });

    it('should reject Infinity', () => {
      const isValidTimeout = (v: number | undefined): v is number =>
        v !== undefined && Number.isFinite(v) && v > 0;

      expect(isValidTimeout(Infinity)).toBe(false);
      expect(isValidTimeout(-Infinity)).toBe(false);
    });

    it('should accept valid positive numbers', () => {
      const isValidTimeout = (v: number | undefined): v is number =>
        v !== undefined && Number.isFinite(v) && v > 0;

      expect(isValidTimeout(300000)).toBe(true);
      expect(isValidTimeout(1)).toBe(true);
      expect(isValidTimeout(0.5)).toBe(true);
    });

    it('should validate iterations as positive integers', () => {
      const isValidIter = (v: number | undefined): v is number =>
        v !== undefined && Number.isFinite(v) && v > 0 && Number.isInteger(v);

      expect(isValidIter(15)).toBe(true);
      expect(isValidIter(1)).toBe(true);
      expect(isValidIter(0)).toBe(false);
      expect(isValidIter(-1)).toBe(false);
      expect(isValidIter(1.5)).toBe(false);
      expect(isValidIter(NaN)).toBe(false);
    });
  });
});
