/**
 * SWE-bench Grader
 *
 * Grades SWE-bench tasks by checking if the agent generated a valid patch.
 * For full grading, use the official SWE-bench harness separately.
 */

import type { EvalTask, Grader, AgentOutput, GradeResult } from '../types.js';
import { extractGitDiff, gradeSimple } from '../adapters/swe-bench.js';
import * as path from 'path';

export class SWEBenchGrader implements Grader {
  readonly type = 'swe-bench' as const;

  /**
   * Grade a SWE-bench task.
   *
   * This grader checks if the agent:
   * 1. Generated any changes (git diff)
   * 2. The changes appear to be a valid patch
   *
   * For full test-based grading, run the official SWE-bench harness
   * on the predictions.jsonl file after all tasks complete.
   */
  async grade(task: EvalTask, agentOutput: AgentOutput, _workdir: string): Promise<GradeResult> {
    // Get the instance_id from task metadata
    const sweBenchMeta = task.expected?.swe_bench;
    if (!sweBenchMeta) {
      return {
        success: false,
        partial_credit: 0,
        explanation: 'Task missing SWE-bench metadata',
      };
    }

    // The workspace directory for this instance
    const instanceWorkdir = path.join('/tmp/swe-bench-workspace', sweBenchMeta.instance_id);

    // Check if agent made any changes
    const patch = extractGitDiff(instanceWorkdir);

    // Use simple grading
    const result = gradeSimple(
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

    return result;
  }
}
