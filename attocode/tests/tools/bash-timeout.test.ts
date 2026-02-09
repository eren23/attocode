/**
 * Tests for the bash timeout heuristic (normalizeTimeoutMs).
 *
 * Models often send timeout values in seconds (e.g. 60) when the bash tool
 * expects milliseconds. normalizeTimeoutMs auto-converts values < 300 to ms.
 */

import { describe, it, expect } from 'vitest';
import { normalizeTimeoutMs } from '../../src/tools/bash.js';

describe('normalizeTimeoutMs', () => {
  it('converts small positive values (seconds) to milliseconds', () => {
    expect(normalizeTimeoutMs(60)).toBe(60_000);
    expect(normalizeTimeoutMs(1)).toBe(1_000);
    expect(normalizeTimeoutMs(120)).toBe(120_000);
    expect(normalizeTimeoutMs(299)).toBe(299_000);
  });

  it('does not convert values >= 300 (already milliseconds)', () => {
    expect(normalizeTimeoutMs(300)).toBe(300);
    expect(normalizeTimeoutMs(500)).toBe(500);
    expect(normalizeTimeoutMs(30000)).toBe(30000);
    expect(normalizeTimeoutMs(60000)).toBe(60000);
  });

  it('does not convert zero', () => {
    expect(normalizeTimeoutMs(0)).toBe(0);
  });

  it('does not convert negative values', () => {
    expect(normalizeTimeoutMs(-1)).toBe(-1);
    expect(normalizeTimeoutMs(-100)).toBe(-100);
  });
});
