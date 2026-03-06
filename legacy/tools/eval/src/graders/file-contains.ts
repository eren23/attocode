/**
 * File Contains Grader
 *
 * Grades tasks by checking if specified files contain expected content.
 */

import type { EvalTask, Grader, AgentOutput, GradeResult } from '../types.js';
import * as fs from 'fs/promises';
import * as path from 'path';

export class FileContainsGrader implements Grader {
  type = 'file-contains' as const;

  async grade(
    task: EvalTask,
    agentOutput: AgentOutput,
    workdir: string
  ): Promise<GradeResult> {
    const expected = task.expected;

    if (!expected?.file_contains) {
      return {
        success: agentOutput.success,
        partial_credit: agentOutput.success ? 1 : 0,
        explanation: 'No file_contains specified, using agent success status',
      };
    }

    const fileChecks = Object.entries(expected.file_contains);
    let matched = 0;
    const failures: string[] = [];

    for (const [filePath, expectedContent] of fileChecks) {
      const fullPath = path.join(workdir, filePath);

      try {
        const content = await fs.readFile(fullPath, 'utf-8');


        // Support both single string and array of patterns
        const patterns = Array.isArray(expectedContent) ? expectedContent : [expectedContent];
        let fileMatched = true;

        for (const pattern of patterns) {
          if (!content.includes(pattern)) {
            fileMatched = false;
            failures.push(`${filePath}: missing "${pattern.slice(0, 50)}..."`);
            break;
          }
        }

        if (fileMatched) {
          matched++;
        }
      } catch {
        failures.push(`${filePath}: file not found`);
      }
    }

    const total = fileChecks.length;
    const partialCredit = total > 0 ? matched / total : 0;

    return {
      success: matched === total,
      partial_credit: partialCredit,
      explanation: matched === total
        ? `All ${total} file checks passed`
        : `${matched}/${total} file checks passed`,
      details: {
        content_matches: { matched, total },
      },
    };
  }
}
