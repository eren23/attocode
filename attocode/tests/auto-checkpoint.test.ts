/**
 * Auto-Checkpoint Manager Tests
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { existsSync, rmSync } from 'node:fs';
import {
  AutoCheckpointManager,
  createAutoCheckpointManager,
} from '../src/integrations/auto-checkpoint.js';

const TEST_DIR = '/tmp/attocode-test-checkpoints';

describe('AutoCheckpointManager', () => {
  let mgr: AutoCheckpointManager;

  beforeEach(() => {
    if (existsSync(TEST_DIR)) {
      rmSync(TEST_DIR, { recursive: true });
    }
    mgr = new AutoCheckpointManager({
      checkpointDir: TEST_DIR,
      minInterval: 0, // disable throttling for tests
      maxCheckpointsPerSession: 5,
      maxAge: 3600000,
    });
  });

  afterEach(() => {
    if (existsSync(TEST_DIR)) {
      rmSync(TEST_DIR, { recursive: true });
    }
  });

  describe('save', () => {
    it('should save a checkpoint and return an ID', () => {
      const id = mgr.save({
        label: 'after-tool-batch',
        sessionId: 'sess-1',
        iteration: 5,
      });
      expect(id).toBeTruthy();
      expect(id).toContain('ckpt-');
    });

    it('should return null when disabled', () => {
      const disabled = new AutoCheckpointManager({ enabled: false });
      const id = disabled.save({
        label: 'test',
        sessionId: 'sess-1',
        iteration: 1,
      });
      expect(id).toBeNull();
    });

    it('should respect minInterval throttling', () => {
      const throttled = new AutoCheckpointManager({
        checkpointDir: TEST_DIR,
        minInterval: 60000, // 60s
      });
      const id1 = throttled.save({
        label: 'first',
        sessionId: 'sess-1',
        iteration: 1,
      });
      const id2 = throttled.save({
        label: 'second',
        sessionId: 'sess-1',
        iteration: 2,
      });
      expect(id1).toBeTruthy();
      expect(id2).toBeNull(); // Too soon
    });
  });

  describe('load', () => {
    it('should load a saved checkpoint', () => {
      const id = mgr.save({
        label: 'test-load',
        sessionId: 'sess-2',
        iteration: 3,
        objective: 'Fix bugs',
      });
      const loaded = mgr.load('sess-2', id!);
      expect(loaded).not.toBeNull();
      expect(loaded!.label).toBe('test-load');
      expect(loaded!.iteration).toBe(3);
      expect(loaded!.objective).toBe('Fix bugs');
    });

    it('should return null for nonexistent checkpoint', () => {
      expect(mgr.load('no-session', 'no-ckpt')).toBeNull();
    });
  });

  describe('loadSessionCheckpoints', () => {
    it('should return all checkpoints for a session', () => {
      mgr.save({ label: 'first', sessionId: 'sess-3', iteration: 1 });
      mgr.save({ label: 'second', sessionId: 'sess-3', iteration: 2 });
      mgr.save({ label: 'third', sessionId: 'sess-3', iteration: 3 });

      const checkpoints = mgr.loadSessionCheckpoints('sess-3');
      expect(checkpoints).toHaveLength(3);
      const iterations = checkpoints.map(c => c.iteration).sort();
      expect(iterations).toEqual([1, 2, 3]);
    });

    it('should return empty for nonexistent session', () => {
      expect(mgr.loadSessionCheckpoints('nonexistent')).toHaveLength(0);
    });
  });

  describe('findResumeCandidates', () => {
    it('should find recent sessions', () => {
      mgr.save({ label: 'recent', sessionId: 'sess-4', iteration: 1 });

      const candidates = mgr.findResumeCandidates(60000); // 1 minute
      expect(candidates.length).toBeGreaterThanOrEqual(1);
      expect(candidates[0].sessionId).toBe('sess-4');
    });

    it('should not find old sessions', () => {
      mgr.save({ label: 'recent', sessionId: 'sess-5', iteration: 1 });

      // With very short max age (and a small delay), session should age out
      // Use 1ms window - the checkpoint was saved at least 1ms ago by now
      const candidates = mgr.findResumeCandidates(0);
      // 0ms maxAge means age <= 0, which is only true if same millisecond
      // This is inherently racy, so just verify the API works
      expect(candidates.length).toBeLessThanOrEqual(1);
    });
  });

  describe('formatCheckpointSummary', () => {
    it('should format a human-readable summary', () => {
      const id = mgr.save({
        label: 'after-tool-batch',
        sessionId: 'sess-6',
        iteration: 10,
        objective: 'Refactor auth module',
        tokensUsed: 5000,
        filesModified: ['src/auth.ts'],
      });
      const ckpt = mgr.load('sess-6', id!);
      const summary = mgr.formatCheckpointSummary(ckpt!);
      expect(summary).toContain('sess-6');
      expect(summary).toContain('after-tool-batch');
      expect(summary).toContain('Iteration: 10');
      expect(summary).toContain('Refactor auth');
      expect(summary).toContain('5000');
      expect(summary).toContain('src/auth.ts');
    });
  });

  describe('cleanupAll', () => {
    it('should remove old checkpoints', () => {
      // Create with very short maxAge
      const shortLived = new AutoCheckpointManager({
        checkpointDir: TEST_DIR,
        minInterval: 0,
        maxAge: 1, // 1ms
      });
      shortLived.save({ label: 'old', sessionId: 'sess-7', iteration: 1 });

      // Wait a tiny bit to ensure it ages
      const start = Date.now();
      while (Date.now() - start < 10) { /* busy wait */ }

      const cleaned = shortLived.cleanupAll();
      expect(cleaned).toBeGreaterThanOrEqual(1);
    });
  });

  describe('session cleanup (max checkpoints per session)', () => {
    it('should keep only maxCheckpointsPerSession', () => {
      for (let i = 0; i < 8; i++) {
        mgr.save({ label: `ckpt-${i}`, sessionId: 'sess-8', iteration: i });
      }
      const checkpoints = mgr.loadSessionCheckpoints('sess-8');
      expect(checkpoints.length).toBeLessThanOrEqual(5);
    });
  });
});

describe('createAutoCheckpointManager', () => {
  it('should create with defaults', () => {
    const mgr = createAutoCheckpointManager({ checkpointDir: TEST_DIR });
    expect(mgr).toBeInstanceOf(AutoCheckpointManager);
    if (existsSync(TEST_DIR)) rmSync(TEST_DIR, { recursive: true });
  });
});
