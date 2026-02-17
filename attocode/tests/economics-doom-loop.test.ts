/**
 * Economics Doom Loop Detection Tests
 *
 * Tests for exact-match and fuzzy doom loop detection.
 */

import { describe, it, expect } from 'vitest';
import {
  computeToolFingerprint,
  createEconomicsManager,
  STANDARD_BUDGET,
} from '../src/integrations/budget/economics.js';
import { DOOM_LOOP_PROMPT } from '../src/integrations/budget/loop-detector.js';

// =============================================================================
// computeToolFingerprint TESTS
// =============================================================================

describe('computeToolFingerprint', () => {
  it('should extract primary args (path)', () => {
    const fp1 = computeToolFingerprint('read_file', JSON.stringify({ path: 'foo.ts' }));
    const fp2 = computeToolFingerprint('read_file', JSON.stringify({ path: 'foo.ts', encoding: 'utf8' }));

    // Same primary arg -> same fingerprint
    expect(fp1).toBe(fp2);
  });

  it('should distinguish different primary args', () => {
    const fp1 = computeToolFingerprint('read_file', JSON.stringify({ path: 'foo.ts' }));
    const fp2 = computeToolFingerprint('read_file', JSON.stringify({ path: 'bar.ts' }));

    expect(fp1).not.toBe(fp2);
  });

  it('should distinguish different tools with same args', () => {
    const fp1 = computeToolFingerprint('read_file', JSON.stringify({ path: 'foo.ts' }));
    const fp2 = computeToolFingerprint('write_file', JSON.stringify({ path: 'foo.ts' }));

    expect(fp1).not.toBe(fp2);
  });

  it('should handle command args (bash)', () => {
    const fp1 = computeToolFingerprint('bash', JSON.stringify({ command: 'ls -la' }));
    const fp2 = computeToolFingerprint('bash', JSON.stringify({ command: 'ls -la', timeout: 5000 }));

    // Same command -> same fingerprint (ignoring timeout)
    expect(fp1).toBe(fp2);
  });

  it('should handle empty args', () => {
    const fp = computeToolFingerprint('some_tool', '{}');
    expect(fp).toContain('some_tool');
  });

  it('should handle malformed JSON gracefully', () => {
    const fp = computeToolFingerprint('tool', 'not-json');
    expect(fp).toBe('tool:not-json');
  });

  it('should handle args with no primary keys', () => {
    const fp1 = computeToolFingerprint('tool', JSON.stringify({ foo: 'bar' }));
    const fp2 = computeToolFingerprint('tool', JSON.stringify({ foo: 'baz' }));

    // No primary keys -> falls back to full args (different)
    expect(fp1).not.toBe(fp2);
  });

  it('should distinguish read_file calls with different offsets', () => {
    const fp1 = computeToolFingerprint('read_file', JSON.stringify({ file_path: '/big.ts', offset: 0, limit: 100 }));
    const fp2 = computeToolFingerprint('read_file', JSON.stringify({ file_path: '/big.ts', offset: 100, limit: 100 }));
    const fp3 = computeToolFingerprint('read_file', JSON.stringify({ file_path: '/big.ts', offset: 200, limit: 100 }));

    // Different offsets -> different fingerprints (no false doom loop)
    expect(fp1).not.toBe(fp2);
    expect(fp2).not.toBe(fp3);
  });

  it('should still match read_file calls with same offset', () => {
    const fp1 = computeToolFingerprint('read_file', JSON.stringify({ file_path: '/big.ts', offset: 0 }));
    const fp2 = computeToolFingerprint('read_file', JSON.stringify({ file_path: '/big.ts', offset: 0, encoding: 'utf8' }));

    // Same primary keys (file_path + offset) -> same fingerprint
    expect(fp1).toBe(fp2);
  });
});

// =============================================================================
// Doom Loop Detection Integration Tests
// =============================================================================

describe('Doom Loop Detection', () => {
  it('should detect exact doom loop at threshold 3', () => {
    const economics = createEconomicsManager(STANDARD_BUDGET);

    const args = { path: '/foo.ts' };

    // Call same tool with identical args 3 times
    economics.recordToolCall('read_file', args);
    economics.recordToolCall('read_file', args);
    economics.recordToolCall('read_file', args);

    const loopState = economics.getLoopState();
    expect(loopState.doomLoopDetected).toBe(true);
    expect(loopState.consecutiveCount).toBeGreaterThanOrEqual(3);
  });

  it('should not trigger on different tool calls', () => {
    const economics = createEconomicsManager(STANDARD_BUDGET);

    economics.recordToolCall('read_file', { path: '/a.ts' });
    economics.recordToolCall('read_file', { path: '/b.ts' });
    economics.recordToolCall('read_file', { path: '/c.ts' });

    const loopState = economics.getLoopState();
    expect(loopState.doomLoopDetected).toBe(false);
  });

  it('should detect fuzzy doom loop with near-identical calls', () => {
    const economics = createEconomicsManager(STANDARD_BUDGET);

    // Same primary arg (path) but different secondary args
    economics.recordToolCall('read_file', { path: '/foo.ts' });
    economics.recordToolCall('read_file', { path: '/foo.ts', encoding: 'utf8' });
    economics.recordToolCall('read_file', { path: '/foo.ts', timeout: 5000 });
    economics.recordToolCall('read_file', { path: '/foo.ts', lines: 100 });

    const loopState = economics.getLoopState();
    // Fuzzy threshold is 4, so this should trigger
    expect(loopState.doomLoopDetected).toBe(true);
  });

  it('should not false-positive on varied primary args', () => {
    const economics = createEconomicsManager(STANDARD_BUDGET);

    // Different primary args each time
    economics.recordToolCall('read_file', { path: '/a.ts' });
    economics.recordToolCall('read_file', { path: '/b.ts' });
    economics.recordToolCall('read_file', { path: '/c.ts' });
    economics.recordToolCall('read_file', { path: '/d.ts' });

    const loopState = economics.getLoopState();
    expect(loopState.doomLoopDetected).toBe(false);
  });

  it('should reset after different tool breaks the sequence', () => {
    const economics = createEconomicsManager(STANDARD_BUDGET);

    economics.recordToolCall('read_file', { path: '/foo.ts' });
    economics.recordToolCall('read_file', { path: '/foo.ts' });
    economics.recordToolCall('write_file', { path: '/bar.ts', content: 'x' }); // Breaks sequence
    economics.recordToolCall('read_file', { path: '/foo.ts' });

    const loopState = economics.getLoopState();
    expect(loopState.doomLoopDetected).toBe(false);
  });

  it('should not trigger doom loop when reading same file with different offsets', () => {
    const economics = createEconomicsManager(STANDARD_BUDGET);

    // Read a large file in 3 chunks — different offsets each time
    economics.recordToolCall('read_file', { file_path: '/big.ts', offset: 0, limit: 100 });
    economics.recordToolCall('read_file', { file_path: '/big.ts', offset: 100, limit: 100 });
    economics.recordToolCall('read_file', { file_path: '/big.ts', offset: 200, limit: 100 });

    const loopState = economics.getLoopState();
    expect(loopState.doomLoopDetected).toBe(false);
  });

  it('should emit doom_loop.detected event', () => {
    const economics = createEconomicsManager(STANDARD_BUDGET);
    const events: Array<{ type: string; tool?: string }> = [];
    economics.on((e) => events.push(e as { type: string; tool?: string }));

    economics.recordToolCall('bash', { command: 'npm test' });
    economics.recordToolCall('bash', { command: 'npm test' });
    economics.recordToolCall('bash', { command: 'npm test' });

    const doomEvents = events.filter(e => e.type === 'doom_loop.detected');
    expect(doomEvents.length).toBeGreaterThanOrEqual(1);
    expect(doomEvents[0].tool).toBe('bash');
  });
});

// =============================================================================
// DOOM_LOOP_PROMPT Escalation Tests
// =============================================================================

describe('DOOM_LOOP_PROMPT escalation', () => {
  it('should return soft warning at count 3', () => {
    const msg = DOOM_LOOP_PROMPT('grep', 3);
    expect(msg).toContain('stuck state');
    expect(msg).not.toContain('CRITICAL');
    expect(msg).not.toContain('WARNING');
  });

  it('should return WARNING at count 4', () => {
    const msg = DOOM_LOOP_PROMPT('grep', 4);
    expect(msg).toContain('WARNING');
    expect(msg).not.toContain('CRITICAL');
  });

  it('should return WARNING at count 5', () => {
    const msg = DOOM_LOOP_PROMPT('grep', 5);
    expect(msg).toContain('WARNING');
  });

  it('should return CRITICAL at count 6+', () => {
    const msg6 = DOOM_LOOP_PROMPT('bash', 6);
    expect(msg6).toContain('CRITICAL');
    expect(msg6).toContain('doom loop');
    expect(msg6).toContain('rejected');

    const msg10 = DOOM_LOOP_PROMPT('bash', 10);
    expect(msg10).toContain('CRITICAL');
  });
});
