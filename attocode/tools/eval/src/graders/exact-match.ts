/**
 * Exact Match Grader
 *
 * Grades tasks by comparing output to expected exact values.
 */

import type { EvalTask, Grader, AgentOutput, GradeResult } from '../types.js';

export class ExactMatchGrader implements Grader {
  type = 'exact-match' as const;

  async grade(
    task: EvalTask,
    agentOutput: AgentOutput,
    _workdir: string
  ): Promise<GradeResult> {
    const expected = task.expected;

    if (!expected?.output) {
      return {
        success: agentOutput.success,
        partial_credit: agentOutput.success ? 1 : 0,
        explanation: 'No expected output specified, using agent success status',
      };
    }

    const actualOutput = agentOutput.response.trim();
    const expectedOutput = expected.output.trim();

    // Exact match
    if (actualOutput === expectedOutput) {
      return {
        success: true,
        partial_credit: 1,
        explanation: 'Output matches exactly',
      };
    }

    // Calculate similarity for partial credit
    const similarity = this.calculateSimilarity(actualOutput, expectedOutput);

    return {
      success: false,
      partial_credit: similarity,
      explanation: `Output differs from expected (${(similarity * 100).toFixed(0)}% similar)`,
      details: {
        content_matches: {
          matched: similarity > 0.5 ? 1 : 0,
          total: 1,
        },
      },
    };
  }

  /**
   * Calculate Levenshtein distance-based similarity.
   */
  private calculateSimilarity(a: string, b: string): number {
    if (a === b) return 1;
    if (a.length === 0 || b.length === 0) return 0;

    const matrix: number[][] = [];

    // Initialize matrix
    for (let i = 0; i <= a.length; i++) {
      matrix[i] = [i];
    }
    for (let j = 0; j <= b.length; j++) {
      matrix[0][j] = j;
    }

    // Fill matrix
    for (let i = 1; i <= a.length; i++) {
      for (let j = 1; j <= b.length; j++) {
        const cost = a[i - 1] === b[j - 1] ? 0 : 1;
        matrix[i][j] = Math.min(
          matrix[i - 1][j] + 1,      // deletion
          matrix[i][j - 1] + 1,      // insertion
          matrix[i - 1][j - 1] + cost // substitution
        );
      }
    }

    const distance = matrix[a.length][b.length];
    const maxLen = Math.max(a.length, b.length);
    return 1 - distance / maxLen;
  }
}
