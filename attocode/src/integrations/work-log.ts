/**
 * Work Log - Compaction-Resilient Structured Summary
 *
 * Maintains a persistent structured summary of agent work that survives
 * context compaction. Auto-populated from tool execution results.
 *
 * When context is compacted, the work log is injected as a system message
 * so the agent doesn't "forget" what it has already done (preventing
 * re-reading files, re-searching, etc.).
 */

// =============================================================================
// TYPES
// =============================================================================

export interface WorkLogEntry {
  timestamp: number;
  type: 'file_read' | 'file_edit' | 'search' | 'test_run' | 'command' | 'approach';
  summary: string;
}

export interface TestResult {
  test: string;
  passed: boolean;
  error?: string;
}

export interface ApproachEntry {
  approach: string;
  outcome: 'success' | 'failure' | 'partial';
  detail?: string;
}

export interface WorkLogConfig {
  /** Maximum number of entries per category before oldest are dropped */
  maxEntriesPerCategory?: number;
  /** Maximum token count for compact output */
  maxCompactTokens?: number;
}

// =============================================================================
// WORK LOG
// =============================================================================

export class WorkLog {
  private currentHypothesis: string = '';
  private filesRead: Map<string, string> = new Map();      // path → 1-line summary
  private filesModified: Map<string, string> = new Map();   // path → what changed
  private testResults: TestResult[] = [];
  private approachesTried: ApproachEntry[] = [];
  private commands: string[] = [];
  private config: Required<WorkLogConfig>;

  constructor(config: WorkLogConfig = {}) {
    this.config = {
      maxEntriesPerCategory: config.maxEntriesPerCategory ?? 30,
      maxCompactTokens: config.maxCompactTokens ?? 1500,
    };
  }

  /**
   * Record a tool execution result into the work log.
   * Called automatically after each tool call in agent.ts.
   */
  recordToolExecution(
    toolName: string,
    args: Record<string, unknown>,
    result?: unknown,
  ): void {
    const resultStr = typeof result === 'string' ? result : '';

    switch (toolName) {
      case 'read_file': {
        const filePath = String(args.path || args.file_path || '');
        if (filePath && !this.filesRead.has(filePath)) {
          // Extract a brief summary from the first few lines of content
          const summary = this.summarizeFileContent(resultStr);
          this.filesRead.set(filePath, summary);
          this.trimMap(this.filesRead, this.config.maxEntriesPerCategory);
        }
        break;
      }

      case 'write_file':
      case 'edit_file': {
        const filePath = String(args.path || args.file_path || '');
        if (filePath) {
          const desc = toolName === 'write_file'
            ? 'created/overwritten'
            : `edited: ${String(args.old_text || '').slice(0, 50)}...`;
          this.filesModified.set(filePath, desc);
          this.trimMap(this.filesModified, this.config.maxEntriesPerCategory);
        }
        break;
      }

      case 'bash': {
        const cmd = String(args.command || '');
        if (cmd) {
          this.commands.push(cmd.slice(0, 200));
          if (this.commands.length > this.config.maxEntriesPerCategory) {
            this.commands.shift();
          }

          // Detect test results from bash output
          this.parseTestResults(cmd, resultStr);
        }
        break;
      }

      case 'grep':
      case 'glob':
      case 'search':
      case 'search_files':
      case 'find_files': {
        const pattern = String(args.pattern || args.query || '');
        if (pattern) {
          const key = `search:${pattern}`;
          this.filesRead.set(key, `Searched for: ${pattern}`);
        }
        break;
      }
    }
  }

  /**
   * Record an approach the agent tried and its outcome.
   */
  recordApproach(approach: string, outcome: ApproachEntry['outcome'], detail?: string): void {
    this.approachesTried.push({ approach, outcome, detail });
    if (this.approachesTried.length > this.config.maxEntriesPerCategory) {
      this.approachesTried.shift();
    }
  }

  /**
   * Set the current working hypothesis.
   */
  setHypothesis(hypothesis: string): void {
    this.currentHypothesis = hypothesis;
  }

  /**
   * Generate a compact string representation (~500 tokens) for injection
   * after context compaction.
   */
  toCompactString(): string {
    const sections: string[] = [];

    sections.push('[WORK LOG - What you have already done in this session]');

    if (this.currentHypothesis) {
      sections.push(`Hypothesis: ${this.currentHypothesis}`);
    }

    // Files read
    if (this.filesRead.size > 0) {
      const fileEntries = Array.from(this.filesRead.entries())
        .filter(([k]) => !k.startsWith('search:'))
        .slice(-15)
        .map(([path, summary]) => `  ${path}: ${summary}`)
        .join('\n');
      if (fileEntries) {
        sections.push(`Files read (${this.filesRead.size} total):\n${fileEntries}`);
      }
    }

    // Files modified
    if (this.filesModified.size > 0) {
      const modEntries = Array.from(this.filesModified.entries())
        .map(([path, desc]) => `  ${path}: ${desc}`)
        .join('\n');
      sections.push(`Files modified:\n${modEntries}`);
    }

    // Test results (most recent)
    if (this.testResults.length > 0) {
      const recentTests = this.testResults.slice(-5);
      const testLines = recentTests.map(t =>
        `  ${t.passed ? 'PASS' : 'FAIL'}: ${t.test}${t.error ? ` (${t.error.slice(0, 80)})` : ''}`
      ).join('\n');
      sections.push(`Test results:\n${testLines}`);
    }

    // Approaches tried
    if (this.approachesTried.length > 0) {
      const approachLines = this.approachesTried.map(a =>
        `  [${a.outcome}] ${a.approach}${a.detail ? `: ${a.detail}` : ''}`
      ).join('\n');
      sections.push(`Approaches tried:\n${approachLines}`);
    }

    // Recent commands
    if (this.commands.length > 0) {
      const recentCmds = this.commands.slice(-5).map(c => `  $ ${c}`).join('\n');
      sections.push(`Recent commands:\n${recentCmds}`);
    }

    sections.push('[END WORK LOG - Do NOT re-read files listed above. Continue from where you left off.]');

    const result = sections.join('\n\n');

    // Enforce maxCompactTokens (~4 chars per token)
    const maxChars = this.config.maxCompactTokens * 4;
    if (result.length > maxChars) {
      return this.toCompactStringTruncated(maxChars);
    }

    return result;
  }

  /**
   * Produce a truncated compact string that fits within the character budget.
   * Keeps fewer entries per category to stay within limits.
   */
  private toCompactStringTruncated(maxChars: number): string {
    const sections: string[] = [];

    sections.push('[WORK LOG - What you have already done in this session]');

    if (this.currentHypothesis) {
      sections.push(`Hypothesis: ${this.currentHypothesis}`);
    }

    // Files modified (always included — most important)
    if (this.filesModified.size > 0) {
      const modEntries = Array.from(this.filesModified.entries())
        .slice(-5)
        .map(([path, desc]) => `  ${path}: ${desc}`)
        .join('\n');
      sections.push(`Files modified:\n${modEntries}`);
    }

    // Files read (top 5 most recent)
    if (this.filesRead.size > 0) {
      const fileEntries = Array.from(this.filesRead.entries())
        .filter(([k]) => !k.startsWith('search:'))
        .slice(-10)
        .map(([path, summary]) => `  ${path}: ${summary}`)
        .join('\n');
      if (fileEntries) {
        sections.push(`Files read (${this.filesRead.size} total, showing last 10):\n${fileEntries}`);
      }
    }

    // Test results (last 3)
    if (this.testResults.length > 0) {
      const recentTests = this.testResults.slice(-5);
      const testLines = recentTests.map(t =>
        `  ${t.passed ? 'PASS' : 'FAIL'}: ${t.test}${t.error ? ` (${t.error.slice(0, 80)})` : ''}`
      ).join('\n');
      sections.push(`Test results:\n${testLines}`);
    }

    // Recent commands (last 3)
    if (this.commands.length > 0) {
      const recentCmds = this.commands.slice(-3).map(c => `  $ ${c}`).join('\n');
      sections.push(`Recent commands:\n${recentCmds}`);
    }

    sections.push('[END WORK LOG - Do NOT re-read files listed above. Continue from where you left off.]');

    let result = sections.join('\n\n');

    // Hard truncation as last resort
    if (result.length > maxChars) {
      result = result.slice(0, maxChars - 30) + '\n\n[... WORK LOG TRUNCATED ...]';
    }

    return result;
  }

  /**
   * Check if the work log has any content worth injecting.
   */
  hasContent(): boolean {
    return this.filesRead.size > 0
      || this.filesModified.size > 0
      || this.testResults.length > 0
      || this.commands.length > 0;
  }

  /**
   * Get basic stats about the work log.
   */
  getStats(): {
    filesRead: number;
    filesModified: number;
    testResults: number;
    approaches: number;
    commands: number;
  } {
    return {
      filesRead: this.filesRead.size,
      filesModified: this.filesModified.size,
      testResults: this.testResults.length,
      approaches: this.approachesTried.length,
      commands: this.commands.length,
    };
  }

  /**
   * Reset the work log.
   */
  reset(): void {
    this.currentHypothesis = '';
    this.filesRead.clear();
    this.filesModified.clear();
    this.testResults = [];
    this.approachesTried = [];
    this.commands = [];
  }

  // ---------------------------------------------------------------------------
  // PRIVATE HELPERS
  // ---------------------------------------------------------------------------

  private summarizeFileContent(content: string): string {
    if (!content) return '(read)';
    const firstLine = content.split('\n').find(l => l.trim().length > 0) || '';
    return firstLine.slice(0, 80) || '(read)';
  }

  private parseTestResults(command: string, output: string): void {
    const isTestCommand = /pytest|python\s+-m\s+pytest|npm\s+test|jest/.test(command);
    if (!isTestCommand || !output) return;

    // Parse pytest-style output: "PASSED" or "FAILED" in output
    const passMatch = output.match(/(\d+)\s+passed/);
    const failMatch = output.match(/(\d+)\s+failed/);

    if (passMatch || failMatch) {
      const passed = passMatch ? parseInt(passMatch[1], 10) : 0;
      const failed = failMatch ? parseInt(failMatch[1], 10) : 0;

      this.testResults.push({
        test: command.slice(0, 100),
        passed: failed === 0 && passed > 0,
        error: failed > 0 ? `${failed} failed, ${passed} passed` : undefined,
      });

      if (this.testResults.length > this.config.maxEntriesPerCategory) {
        this.testResults.shift();
      }
    }
  }

  private trimMap(map: Map<string, string>, maxSize: number): void {
    if (map.size > maxSize) {
      const keysToRemove = Array.from(map.keys()).slice(0, map.size - maxSize);
      for (const key of keysToRemove) {
        map.delete(key);
      }
    }
  }
}

// =============================================================================
// FACTORY
// =============================================================================

export function createWorkLog(config?: WorkLogConfig): WorkLog {
  return new WorkLog(config);
}
