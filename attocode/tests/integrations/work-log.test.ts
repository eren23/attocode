/**
 * Tests for WorkLog - Compaction-Resilient Structured Summary
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { WorkLog, createWorkLog } from '../../src/integrations/tasks/work-log.js';

describe('WorkLog', () => {
  let log: WorkLog;

  beforeEach(() => {
    log = createWorkLog();
  });

  describe('recordToolExecution', () => {
    it('should record file reads', () => {
      log.recordToolExecution('read_file', { path: 'src/main.ts' }, '// main entry point\nconsole.log("hello");');
      const stats = log.getStats();
      expect(stats.filesRead).toBe(1);
    });

    it('should not duplicate file reads', () => {
      log.recordToolExecution('read_file', { path: 'src/main.ts' }, '// content');
      log.recordToolExecution('read_file', { path: 'src/main.ts' }, '// content');
      const stats = log.getStats();
      expect(stats.filesRead).toBe(1);
    });

    it('should record file edits', () => {
      log.recordToolExecution('edit_file', { path: 'src/bug.ts', old_text: 'broken' }, 'fixed');
      const stats = log.getStats();
      expect(stats.filesModified).toBe(1);
    });

    it('should record bash commands', () => {
      log.recordToolExecution('bash', { command: 'ls -la' }, 'file1\nfile2');
      const stats = log.getStats();
      expect(stats.commands).toBe(1);
    });

    it('should parse test results from pytest output', () => {
      log.recordToolExecution(
        'bash',
        { command: 'python -m pytest tests/test_fix.py -xvs' },
        '1 passed, 2 failed\nFAILED tests/test_fix.py::test_one',
      );
      const stats = log.getStats();
      expect(stats.testResults).toBe(1);
    });

    it('should record search operations', () => {
      log.recordToolExecution('grep', { pattern: 'class Foo' }, 'src/foo.ts:1:class Foo');
      const stats = log.getStats();
      expect(stats.filesRead).toBe(1); // search stored in filesRead map
    });
  });

  describe('toCompactString', () => {
    it('should produce a compact summary', () => {
      log.recordToolExecution('read_file', { path: 'src/main.ts' }, '// entry');
      log.recordToolExecution('edit_file', { path: 'src/bug.ts' }, 'fixed');
      log.recordToolExecution('bash', { command: 'pytest' }, '1 passed');
      log.setHypothesis('The bug is in the parser');

      const compact = log.toCompactString();
      expect(compact).toContain('WORK LOG');
      expect(compact).toContain('src/main.ts');
      expect(compact).toContain('src/bug.ts');
      expect(compact).toContain('parser');
      expect(compact).toContain('END WORK LOG');
    });

    it('should include a do-not-re-read warning', () => {
      log.recordToolExecution('read_file', { path: 'foo.ts' }, 'content');
      const compact = log.toCompactString();
      expect(compact).toContain('Do NOT re-read');
    });
  });

  describe('hasContent', () => {
    it('should return false when empty', () => {
      expect(log.hasContent()).toBe(false);
    });

    it('should return true after recording', () => {
      log.recordToolExecution('read_file', { path: 'x.ts' }, '');
      expect(log.hasContent()).toBe(true);
    });
  });

  describe('reset', () => {
    it('should clear all entries', () => {
      log.recordToolExecution('read_file', { path: 'a.ts' }, '');
      log.recordToolExecution('bash', { command: 'ls' }, '');
      log.setHypothesis('test');
      log.reset();

      expect(log.hasContent()).toBe(false);
      const stats = log.getStats();
      expect(stats.filesRead).toBe(0);
      expect(stats.commands).toBe(0);
    });
  });

  describe('recordApproach', () => {
    it('should record approaches', () => {
      log.recordApproach('Fix parser', 'failure', 'wrong class');
      log.recordApproach('Fix tokenizer', 'success');
      const stats = log.getStats();
      expect(stats.approaches).toBe(2);
    });

    it('should include approaches in compact string', () => {
      log.recordApproach('Fix parser', 'failure', 'wrong class');
      const compact = log.toCompactString();
      expect(compact).toContain('Fix parser');
      expect(compact).toContain('failure');
    });
  });

  describe('max entries trimming', () => {
    it('should trim entries when limit is exceeded', () => {
      const smallLog = createWorkLog({ maxEntriesPerCategory: 3 });
      for (let i = 0; i < 10; i++) {
        smallLog.recordToolExecution('bash', { command: `cmd-${i}` }, '');
      }
      const stats = smallLog.getStats();
      expect(stats.commands).toBe(3);
    });
  });

  describe('toCompactString size enforcement', () => {
    it('should truncate output when it exceeds maxCompactTokens', () => {
      // Use a very small token budget to force truncation
      const tinyLog = createWorkLog({ maxCompactTokens: 50, maxEntriesPerCategory: 100 });

      // Add many entries to blow past the budget
      for (let i = 0; i < 50; i++) {
        tinyLog.recordToolExecution('read_file', { path: `src/very/long/path/to/file-${i}.ts` }, `content of file ${i}`);
      }
      for (let i = 0; i < 20; i++) {
        tinyLog.recordToolExecution('bash', { command: `long-command-that-takes-space-${i}` }, '');
      }

      const compact = tinyLog.toCompactString();
      // 50 tokens * 4 chars = 200 chars max
      expect(compact.length).toBeLessThanOrEqual(200);
      expect(compact).toContain('WORK LOG');
    });

    it('should not truncate when within budget', () => {
      // Default budget is 500 tokens = ~2000 chars — plenty for a few entries
      log.recordToolExecution('read_file', { path: 'src/main.ts' }, '// entry');
      log.recordToolExecution('edit_file', { path: 'src/bug.ts' }, 'fixed');

      const compact = log.toCompactString();
      expect(compact).toContain('END WORK LOG');
      expect(compact).not.toContain('TRUNCATED');
    });
  });
});
