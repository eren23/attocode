/**
 * Test-Based Grader
 *
 * Grades tasks by running a test command and checking pass rate.
 */

import type { EvalTask, Grader, AgentOutput, GradeResult } from '../types.js';
import { execFileSync, type SpawnSyncReturns } from 'child_process';

export class TestBasedGrader implements Grader {
  type = 'test-based' as const;

  async grade(
    task: EvalTask,
    agentOutput: AgentOutput,
    workdir: string
  ): Promise<GradeResult> {
    const expected = task.expected;
    const testCommand = expected?.test_command || 'npm test';

    // If agent failed, no point running tests
    if (!agentOutput.success) {
      return {
        success: false,
        partial_credit: 0,
        explanation: 'Agent reported failure, skipping tests',
      };
    }

    try {
      // Parse command into executable and args
      const parts = testCommand.split(' ');
      const executable = parts[0];
      const args = parts.slice(1);

      // Run the test command
      const result = execFileSync(executable, args, {
        cwd: workdir,
        encoding: 'utf-8',
        timeout: task.timeout_ms,
        stdio: ['pipe', 'pipe', 'pipe'],
      });

      // All tests passed
      const passCount = this.extractTestCount(result.toString(), 'pass');
      const totalCount = this.extractTestCount(result.toString(), 'total');

      return {
        success: true,
        partial_credit: 1,
        explanation: `All tests passed (${passCount}/${totalCount || passCount})`,
        details: {
          tests: {
            passed: passCount || 1,
            total: totalCount || passCount || 1,
          },
        },
      };
    } catch (error) {
      // Test command failed
      const execError = error as SpawnSyncReturns<string> & { message?: string };
      const output = execError.stdout?.toString() || execError.stderr?.toString() || '';

      const passCount = this.extractTestCount(output, 'pass');
      const failCount = this.extractTestCount(output, 'fail');
      const totalCount = passCount + failCount;

      const partialCredit = totalCount > 0 ? passCount / totalCount : 0;

      return {
        success: false,
        partial_credit: partialCredit,
        explanation: `Tests failed: ${passCount}/${totalCount} passed`,
        details: {
          tests: {
            passed: passCount,
            total: totalCount,
          },
        },
      };
    }
  }

  /**
   * Extract test counts from output.
   * Handles common test runner output formats.
   */
  private extractTestCount(output: string, type: 'pass' | 'fail' | 'total'): number {
    const patterns: Record<string, RegExp[]> = {
      pass: [
        /(\d+)\s+pass/i,
        /(\d+)\s+passing/i,
        /Tests:\s*(\d+)\s+passed/i,
        /✓\s*(\d+)/,
      ],
      fail: [
        /(\d+)\s+fail/i,
        /(\d+)\s+failing/i,
        /Tests:\s*\d+\s+passed,\s*(\d+)\s+failed/i,
        /✗\s*(\d+)/,
      ],
      total: [
        /(\d+)\s+total/i,
        /Tests:\s*(\d+)/i,
        /Ran\s+(\d+)\s+tests?/i,
      ],
    };

    for (const pattern of patterns[type]) {
      const match = output.match(pattern);
      if (match) {
        return parseInt(match[1], 10);
      }
    }

    return 0;
  }
}
