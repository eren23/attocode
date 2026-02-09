/**
 * Tests for SWE-bench grader with FAIL_TO_PASS test execution.
 *
 * Note: child_process mocking is for execFile (safe subprocess invocation),
 * not exec. The actual grader uses execFile to avoid shell injection.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { parsePytestOutput } from '../../tools/eval/src/graders/swe-bench.js';
import { gradeSimple } from '../../tools/eval/src/adapters/swe-bench.js';
import type { SWEBenchInstance } from '../../tools/eval/src/adapters/swe-bench.js';

// =============================================================================
// gradeSimple regression tests
// =============================================================================

describe('gradeSimple', () => {
  const baseInstance: SWEBenchInstance = {
    instance_id: 'test__test-123',
    repo: 'test/test',
    base_commit: 'abc123',
    problem_statement: 'Fix the bug',
    hints_text: '',
    patch: '',
    test_patch: '',
    version: '1.0',
    FAIL_TO_PASS: '["tests/test_foo.py::test_bar"]',
    PASS_TO_PASS: '[]',
  };

  it('returns 0 credit for no patch', () => {
    const result = gradeSimple(baseInstance, null);
    expect(result.success).toBe(false);
    expect(result.partial_credit).toBe(0);
  });

  it('returns 0.1 for invalid diff', () => {
    const result = gradeSimple(baseInstance, 'this is not a diff');
    expect(result.success).toBe(false);
    expect(result.partial_credit).toBe(0.1);
  });

  it('returns 0.2 for test-only changes', () => {
    const patch = `diff --git a/tests/test_foo.py b/tests/test_foo.py
--- a/tests/test_foo.py
+++ b/tests/test_foo.py
@@ -1 +1 @@
-old
+new`;
    const result = gradeSimple(baseInstance, patch);
    expect(result.success).toBe(false);
    expect(result.partial_credit).toBe(0.2);
  });

  it('returns 0.5 partial credit for valid source patch (not verified)', () => {
    const patch = `diff --git a/src/main.py b/src/main.py
--- a/src/main.py
+++ b/src/main.py
@@ -1 +1 @@
-old
+new`;
    const result = gradeSimple(baseInstance, patch);
    expect(result.success).toBe(false); // Not verified - actual success determined by harness
    expect(result.partial_credit).toBe(0.5);
  });
});

// =============================================================================
// parsePytestOutput tests
// =============================================================================

describe('parsePytestOutput', () => {
  it('parses all-passing output', () => {
    const output = `5 passed in 1.23s`;
    const result = parsePytestOutput(output, 5);
    expect(result.passedTests).toBe(5);
    expect(result.totalTests).toBe(5);
  });

  it('parses mixed pass/fail output', () => {
    const output = `3 failed, 2 passed in 2.34s`;
    const result = parsePytestOutput(output, 5);
    expect(result.passedTests).toBe(2);
    expect(result.totalTests).toBe(5);
  });

  it('parses output with errors', () => {
    const output = `1 passed, 1 failed, 1 error in 3.45s`;
    const result = parsePytestOutput(output, 3);
    expect(result.passedTests).toBe(1);
    expect(result.totalTests).toBe(3);
  });

  it('parses all-failing output', () => {
    const output = `4 failed in 0.50s`;
    const result = parsePytestOutput(output, 4);
    expect(result.passedTests).toBe(0);
    expect(result.totalTests).toBe(4);
  });

  it('falls back to expectedTotal when no counts parsed', () => {
    const output = `some random output with no summary`;
    const result = parsePytestOutput(output, 3);
    expect(result.passedTests).toBe(0);
    expect(result.totalTests).toBe(3);
  });

  it('preserves raw output', () => {
    const output = `FAILED tests/test_foo.py::test_bar\n3 failed in 1.0s`;
    const result = parsePytestOutput(output, 3);
    expect(result.output).toBe(output);
  });
});

// =============================================================================
// SWEBenchGrader.grade() integration tests (mocked subprocess)
// =============================================================================

describe('SWEBenchGrader.grade', () => {
  // We mock child_process (execFile for pytest, execFileSync for git apply),
  // fs (for test patch temp file), and extractGitDiff to test grading logic
  // without real filesystem or subprocess access.

  let SWEBenchGrader: any;
  let mockExecFileFn: ReturnType<typeof vi.fn>;
  let mockExecFileSyncFn: ReturnType<typeof vi.fn>;
  let mockExtractGitDiff: ReturnType<typeof vi.fn>;
  let mockWriteFileSync: ReturnType<typeof vi.fn>;
  let mockUnlinkSync: ReturnType<typeof vi.fn>;

  beforeEach(async () => {
    vi.resetModules();

    // Mock child_process: execFile (async, for pytest) and execFileSync (for git apply)
    mockExecFileFn = vi.fn();
    mockExecFileSyncFn = vi.fn();
    vi.doMock('child_process', () => ({
      execFile: mockExecFileFn,
      execSync: vi.fn(),
      execFileSync: mockExecFileSyncFn,
      spawn: vi.fn(),
    }));

    // Mock fs for applyTestPatch (writeFileSync, unlinkSync)
    mockWriteFileSync = vi.fn();
    mockUnlinkSync = vi.fn();
    vi.doMock('fs', () => ({
      writeFileSync: mockWriteFileSync,
      unlinkSync: mockUnlinkSync,
      readFileSync: vi.fn(),
      existsSync: vi.fn(() => false),
      mkdirSync: vi.fn(),
    }));

    // Mock extractGitDiff
    mockExtractGitDiff = vi.fn();
    vi.doMock('../../tools/eval/src/adapters/swe-bench.js', async () => {
      const actual = await vi.importActual('../../tools/eval/src/adapters/swe-bench.js') as any;
      return {
        ...actual,
        extractGitDiff: mockExtractGitDiff,
      };
    });

    // Re-import grader with mocks
    const mod = await import('../../tools/eval/src/graders/swe-bench.js');
    SWEBenchGrader = mod.SWEBenchGrader;
  });

  function makeTask(opts: { failToPass?: string; testPatch?: string } = {}) {
    return {
      id: 'test__test-123',
      name: 'Test task',
      prompt: 'Fix it',
      timeout_ms: 60000,
      grader: 'swe-bench' as const,
      expected: {
        swe_bench: {
          instance_id: 'test__test-123',
          repo: 'test/test',
          base_commit: 'abc123',
          fail_to_pass: opts.failToPass ?? '["tests/test_foo.py::test_bar"]',
          pass_to_pass: '[]',
          ...(opts.testPatch !== undefined ? { test_patch: opts.testPatch } : {}),
        },
      },
      metadata: {
        difficulty: 'medium' as const,
        category: 'swe-bench' as const,
        source: 'swe-bench-lite' as const,
      },
    };
  }

  const agentOutput = {
    success: true,
    response: 'Done',
    files_modified: [],
    files_created: [],
  };

  const validPatch = `diff --git a/src/main.py b/src/main.py
--- a/src/main.py
+++ b/src/main.py
@@ -1 +1 @@
-old
+new`;

  it('returns 0 when no patch generated', async () => {
    mockExtractGitDiff.mockReturnValue(null);
    const grader = new SWEBenchGrader();
    const result = await grader.grade(makeTask(), agentOutput, '/tmp/test');
    expect(result.success).toBe(false);
    expect(result.partial_credit).toBe(0);
  });

  it('returns 1.0 when all FAIL_TO_PASS tests pass', async () => {
    mockExtractGitDiff.mockReturnValue(validPatch);
    // Simulate pytest exiting with code 0 (all passed)
    mockExecFileFn.mockImplementation((_cmd: string, _args: string[], _opts: any, cb: Function) => {
      cb(null, '1 passed in 0.5s', '');
    });

    const grader = new SWEBenchGrader();
    const result = await grader.grade(makeTask(), agentOutput, '/tmp/test');
    expect(result.success).toBe(true);
    expect(result.partial_credit).toBe(1.0);
    expect(result.details?.tests).toEqual({ passed: 1, total: 1 });
  });

  it('returns proportional score when some tests pass', async () => {
    mockExtractGitDiff.mockReturnValue(validPatch);
    const task = makeTask({
      failToPass: '["tests/test_a.py::test_1", "tests/test_a.py::test_2", "tests/test_a.py::test_3", "tests/test_a.py::test_4"]',
    });

    // Simulate pytest exiting with code 1 (some failed)
    mockExecFileFn.mockImplementation((_cmd: string, _args: string[], _opts: any, cb: Function) => {
      const err = new Error('pytest failed') as any;
      err.code = 1;
      cb(err, '2 failed, 2 passed in 1.0s', '');
    });

    const grader = new SWEBenchGrader();
    const result = await grader.grade(task, agentOutput, '/tmp/test');
    expect(result.success).toBe(false);
    // 0.5 + 0.5 * (2/4) = 0.75
    expect(result.partial_credit).toBe(0.75);
    expect(result.details?.tests).toEqual({ passed: 2, total: 4 });
  });

  it('returns 0.5 when patch exists but no tests pass', async () => {
    mockExtractGitDiff.mockReturnValue(validPatch);
    mockExecFileFn.mockImplementation((_cmd: string, _args: string[], _opts: any, cb: Function) => {
      const err = new Error('pytest failed') as any;
      err.code = 1;
      cb(err, '1 failed in 0.3s', '');
    });

    const grader = new SWEBenchGrader();
    const result = await grader.grade(makeTask(), agentOutput, '/tmp/test');
    expect(result.success).toBe(false);
    expect(result.partial_credit).toBe(0.5);
    expect(result.details?.tests).toEqual({ passed: 0, total: 1 });
  });

  it('falls back to simple grading when pytest times out', async () => {
    mockExtractGitDiff.mockReturnValue(validPatch);
    mockExecFileFn.mockImplementation((_cmd: string, _args: string[], _opts: any, cb: Function) => {
      const err = new Error('timed out') as any;
      err.killed = true;
      cb(err, '', '');
    });

    const grader = new SWEBenchGrader();
    const result = await grader.grade(makeTask(), agentOutput, '/tmp/test');
    // Falls back to simple grading: 0.5 with explanation
    expect(result.partial_credit).toBe(0.5);
    expect(result.explanation).toContain('Tests not run');
  });

  it('falls back to simple grading when no FAIL_TO_PASS tests', async () => {
    mockExtractGitDiff.mockReturnValue(validPatch);
    const task = makeTask({ failToPass: '[]' });

    const grader = new SWEBenchGrader();
    const result = await grader.grade(task, agentOutput, '/tmp/test');
    expect(result.partial_credit).toBe(0.5);
  });

  it('falls back when pytest not found (ENOENT)', async () => {
    mockExtractGitDiff.mockReturnValue(validPatch);
    mockExecFileFn.mockImplementation((_cmd: string, _args: string[], _opts: any, cb: Function) => {
      const err = new Error('spawn python ENOENT') as any;
      err.code = 'ENOENT';
      cb(err, '', '');
    });

    const grader = new SWEBenchGrader();
    const result = await grader.grade(makeTask(), agentOutput, '/tmp/test');
    expect(result.partial_credit).toBe(0.5);
    expect(result.explanation).toContain('Tests not run');
  });

  it('falls back when pytest has collection error (exit code 2)', async () => {
    mockExtractGitDiff.mockReturnValue(validPatch);
    mockExecFileFn.mockImplementation((_cmd: string, _args: string[], _opts: any, cb: Function) => {
      const err = new Error('collection error') as any;
      err.code = 2;
      cb(err, 'ERROR collecting tests', '');
    });

    const grader = new SWEBenchGrader();
    const result = await grader.grade(makeTask(), agentOutput, '/tmp/test');
    expect(result.partial_credit).toBe(0.5);
    expect(result.explanation).toContain('Tests not run');
  });

  // ==========================================================================
  // test_patch application tests
  // ==========================================================================

  it('applies test_patch before running tests when provided', async () => {
    mockExtractGitDiff.mockReturnValue(validPatch);
    // execFileSync for git apply (should succeed)
    mockExecFileSyncFn.mockReturnValue('');
    // execFile for pytest (all pass)
    mockExecFileFn.mockImplementation((_cmd: string, _args: string[], _opts: any, cb: Function) => {
      cb(null, '1 passed in 0.5s', '');
    });

    const task = makeTask({ testPatch: 'diff --git a/tests/test_new.py ...' });
    const grader = new SWEBenchGrader();
    const result = await grader.grade(task, agentOutput, '/tmp/test');

    expect(result.success).toBe(true);
    expect(result.partial_credit).toBe(1.0);
    // Verify test_patch was written and git apply was called
    expect(mockWriteFileSync).toHaveBeenCalledOnce();
    expect(mockExecFileSyncFn).toHaveBeenCalledWith(
      'git',
      expect.arrayContaining(['apply', '--allow-empty']),
      expect.objectContaining({ cwd: '/tmp/test' }),
    );
    // Verify cleanup
    expect(mockUnlinkSync).toHaveBeenCalledOnce();
  });

  it('continues with tests even if test_patch fails to apply', async () => {
    mockExtractGitDiff.mockReturnValue(validPatch);
    // execFileSync for git apply (fails)
    mockExecFileSyncFn.mockImplementation(() => {
      throw new Error('patch does not apply');
    });
    // execFile for pytest (collection error since tests dont exist)
    mockExecFileFn.mockImplementation((_cmd: string, _args: string[], _opts: any, cb: Function) => {
      const err = new Error('collection error') as any;
      err.code = 2;
      cb(err, 'ERROR collecting tests', '');
    });

    const task = makeTask({ testPatch: 'bad patch content' });
    const grader = new SWEBenchGrader();
    const result = await grader.grade(task, agentOutput, '/tmp/test');

    // Falls back to simple grading since tests couldn't run
    expect(result.partial_credit).toBe(0.5);
    expect(result.explanation).toContain('Tests not run');
    // Still attempted cleanup of temp file
    expect(mockUnlinkSync).toHaveBeenCalled();
  });

  it('does not call git apply when no test_patch provided', async () => {
    mockExtractGitDiff.mockReturnValue(validPatch);
    mockExecFileFn.mockImplementation((_cmd: string, _args: string[], _opts: any, cb: Function) => {
      cb(null, '1 passed in 0.5s', '');
    });

    const task = makeTask(); // no testPatch
    const grader = new SWEBenchGrader();
    await grader.grade(task, agentOutput, '/tmp/test');

    // Should not have written any temp file or called git apply
    expect(mockWriteFileSync).not.toHaveBeenCalled();
    expect(mockExecFileSyncFn).not.toHaveBeenCalled();
  });

  it('test_patch applied + all tests pass = full credit with test details', async () => {
    mockExtractGitDiff.mockReturnValue(validPatch);
    mockExecFileSyncFn.mockReturnValue('');
    mockExecFileFn.mockImplementation((_cmd: string, _args: string[], _opts: any, cb: Function) => {
      cb(null, '2 passed in 1.0s', '');
    });

    const task = makeTask({
      failToPass: '["tests/test_new.py::test_a", "tests/test_new.py::test_b"]',
      testPatch: 'diff --git a/tests/test_new.py ...',
    });
    const grader = new SWEBenchGrader();
    const result = await grader.grade(task, agentOutput, '/tmp/test');

    expect(result.success).toBe(true);
    expect(result.partial_credit).toBe(1.0);
    expect(result.details?.tests).toEqual({ passed: 2, total: 2 });
  });
});
