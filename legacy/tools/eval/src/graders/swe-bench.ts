/**
 * SWE-bench Grader
 *
 * Grades SWE-bench tasks by checking if the agent generated a valid patch,
 * then optionally running FAIL_TO_PASS tests in the worktree for real verification.
 */

import type { EvalTask, Grader, AgentOutput, GradeResult } from '../types.js';
import { extractGitDiff, gradeSimple } from '../adapters/swe-bench.js';
import { execFile, execFileSync } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';

// =============================================================================
// TEST RUNNER
// =============================================================================

export interface TestRunResult {
  totalTests: number;
  passedTests: number;
  output: string;
}

/**
 * Run FAIL_TO_PASS tests via pytest in the worktree.
 *
 * @param failToPassJson - JSON string array of pytest test identifiers
 * @param workdir - The worktree directory to run tests in
 * @param timeoutMs - Timeout for pytest execution (default 120s)
 * @returns Test results, or null if tests couldn't be run
 */
export function runFailToPassTests(
  failToPassJson: string,
  workdir: string,
  timeoutMs: number = 120_000,
): Promise<TestRunResult | null> {
  // Parse FAIL_TO_PASS test identifiers
  let testIds: string[];
  try {
    testIds = JSON.parse(failToPassJson);
  } catch {
    return Promise.resolve(null);
  }

  if (!Array.isArray(testIds) || testIds.length === 0) {
    return Promise.resolve(null);
  }

  return new Promise((resolve) => {
    const args = ['-m', 'pytest', ...testIds, '--tb=short', '-q'];

    execFile('python', args, {
      cwd: workdir,
      timeout: timeoutMs,
      maxBuffer: 5 * 1024 * 1024, // 5MB
      env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' },
    }, (error, stdout, stderr) => {
      const output = (stdout || '') + (stderr || '');

      if (error && (error as NodeJS.ErrnoException).code === 'ENOENT') {
        // python not found
        resolve(null);
        return;
      }

      if (error && error.killed) {
        // Timed out
        resolve(null);
        return;
      }

      // Parse pytest output for pass/fail counts
      // pytest exit codes: 0 = all passed, 1 = some failed, 2+ = error
      const exitCode = error ? (error as any).code ?? 2 : 0;

      if (typeof exitCode === 'number' && exitCode >= 2) {
        // Collection error, internal error, etc. — can't trust results
        resolve(null);
        return;
      }

      // Parse the summary line: "X passed, Y failed" or "X passed"
      const parsed = parsePytestOutput(output, testIds.length);
      resolve(parsed);
    });
  });
}

/**
 * Parse pytest -q output to extract pass/fail counts.
 *
 * Looks for summary lines like:
 *   "5 passed in 1.23s"
 *   "3 failed, 2 passed in 2.34s"
 *   "1 passed, 1 failed, 1 error in 3.45s"
 */
export function parsePytestOutput(output: string, expectedTotal: number): TestRunResult {
  let passedTests = 0;
  let failedTests = 0;

  // Match "N passed"
  const passedMatch = output.match(/(\d+)\s+passed/);
  if (passedMatch) {
    passedTests = parseInt(passedMatch[1], 10);
  }

  // Match "N failed"
  const failedMatch = output.match(/(\d+)\s+failed/);
  if (failedMatch) {
    failedTests = parseInt(failedMatch[1], 10);
  }

  // Match "N error"
  const errorMatch = output.match(/(\d+)\s+error/);
  const errorCount = errorMatch ? parseInt(errorMatch[1], 10) : 0;

  const totalTests = passedTests + failedTests + errorCount || expectedTotal;

  return {
    totalTests,
    passedTests,
    output,
  };
}

// =============================================================================
// TEST PATCH APPLICATION
// =============================================================================

/**
 * Apply a test_patch to the worktree so FAIL_TO_PASS tests can be collected.
 *
 * Many SWE-bench tasks include tests that only exist in the test_patch (not at base_commit).
 * Without applying the test_patch first, pytest gets a collection error (exit code 2).
 *
 * @param testPatch - The git patch containing test additions
 * @param workdir - The worktree directory
 * @returns true on success, false on failure
 */
export function applyTestPatch(testPatch: string, workdir: string): boolean {
  const tmpFile = path.join(workdir, `.test_patch_${Date.now()}.diff`);
  try {
    fs.writeFileSync(tmpFile, testPatch);
    execFileSync('git', ['apply', '--allow-empty', tmpFile], {
      cwd: workdir,
      timeout: 30_000,
    });
    return true;
  } catch (error) {
    console.log(`  [grading] Failed to apply test_patch: ${error instanceof Error ? error.message : error}`);
    return false;
  } finally {
    try { fs.unlinkSync(tmpFile); } catch { /* ignore cleanup errors */ }
  }
}

// =============================================================================
// GRADER
// =============================================================================

export class SWEBenchGrader implements Grader {
  readonly type = 'swe-bench' as const;

  /**
   * Grade a SWE-bench task.
   *
   * Grading pipeline:
   * 1. Extract git diff (patch validation)
   * 2. Run basic patch validation via gradeSimple()
   * 3. If patch exists and FAIL_TO_PASS tests are defined, run them in the worktree
   * 4. Score based on test results (or fall back to simple grading)
   *
   * @param task - The eval task
   * @param agentOutput - Agent's output
   * @param workdir - Working directory (worktree or legacy /tmp path)
   */
  async grade(task: EvalTask, agentOutput: AgentOutput, workdir: string): Promise<GradeResult> {
    // Get the instance_id from task metadata
    const sweBenchMeta = task.expected?.swe_bench;
    if (!sweBenchMeta) {
      return {
        success: false,
        partial_credit: 0,
        explanation: 'Task missing SWE-bench metadata',
      };
    }

    // Use the provided workdir (from isolation env) if it looks like a real workspace,
    // otherwise fall back to the legacy hardcoded path
    const instanceWorkdir = workdir && workdir !== process.cwd()
      ? workdir
      : path.join('/tmp/swe-bench-workspace', sweBenchMeta.instance_id);

    // Check if agent made any changes
    const patch = extractGitDiff(instanceWorkdir);

    // Run basic patch validation
    const simpleResult = gradeSimple(
      {
        instance_id: sweBenchMeta.instance_id,
        repo: sweBenchMeta.repo,
        base_commit: sweBenchMeta.base_commit,
        problem_statement: '',
        hints_text: '',
        patch: '',
        test_patch: '',
        version: '',
        FAIL_TO_PASS: sweBenchMeta.fail_to_pass || '[]',
        PASS_TO_PASS: sweBenchMeta.pass_to_pass || '[]',
      },
      patch
    );

    // Store the patch for later full evaluation
    if (patch) {
      (agentOutput as AgentOutput & { swe_bench_patch?: string }).swe_bench_patch = patch;
    }

    // If no valid patch, return simple result as-is (0 or 0.1 or 0.2)
    if (simpleResult.partial_credit < 0.5) {
      return { ...simpleResult, swe_bench_patch: patch || undefined };
    }

    // Patch exists and looks valid — apply test_patch and run FAIL_TO_PASS tests
    if (sweBenchMeta.test_patch) {
      const applied = applyTestPatch(sweBenchMeta.test_patch, instanceWorkdir);
      if (applied) {
        console.log(`  [grading] Applied test_patch successfully`);
      }
      // Continue even if test_patch fails — tests might still exist at base_commit
    }

    const failToPass = sweBenchMeta.fail_to_pass || '[]';
    const testResult = await runFailToPassTests(failToPass, instanceWorkdir);

    if (!testResult) {
      // Tests couldn't run (no pytest, no FAIL_TO_PASS, timeout, collection error)
      // Fall back to simple grading
      console.log(`  [grading] FAIL_TO_PASS tests not run (pytest error or timeout)`);
      return {
        ...simpleResult,
        swe_bench_patch: patch || undefined,
        explanation: `${simpleResult.explanation} | Tests not run (pytest unavailable or errored)`,
      };
    }

    if (testResult.totalTests === 0) {
      // No FAIL_TO_PASS tests defined — can't verify
      return {
        ...simpleResult,
        swe_bench_patch: patch || undefined,
        explanation: `${simpleResult.explanation} | No FAIL_TO_PASS tests defined`,
      };
    }

    // Score based on test results
    const passRatio = testResult.passedTests / testResult.totalTests;
    const testSummary = `${testResult.passedTests}/${testResult.totalTests} FAIL_TO_PASS tests passing`;
    console.log(`  [grading] FAIL_TO_PASS: ${testSummary}`);

    if (passRatio === 1) {
      // All tests pass — full success
      return {
        success: true,
        partial_credit: 1.0,
        swe_bench_patch: patch || undefined,
        explanation: `All ${testSummary}`,
        details: {
          tests: { passed: testResult.passedTests, total: testResult.totalTests },
        },
      };
    }

    if (testResult.passedTests > 0) {
      // Some tests pass — partial credit between 0.5 and 1.0
      return {
        success: false,
        partial_credit: 0.5 + 0.5 * passRatio,
        swe_bench_patch: patch || undefined,
        explanation: `Partial: ${testSummary}`,
        details: {
          tests: { passed: testResult.passedTests, total: testResult.totalTests },
        },
      };
    }

    // No tests pass — patch generated but didn't fix anything
    return {
      success: false,
      partial_credit: 0.5,
      swe_bench_patch: patch || undefined,
      explanation: `Patch generated but ${testSummary}`,
      details: {
        tests: { passed: 0, total: testResult.totalTests },
      },
    };
  }
}
