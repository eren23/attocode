/**
 * Verification Gate - Opt-in Completion Verification
 *
 * Prevents premature completion by checking if required verification
 * steps (like running tests) have been performed before allowing
 * the agent to stop.
 *
 * Configuration:
 * - TUI mode: off by default
 * - Eval mode: auto-configured from FAIL_TO_PASS tests
 * - Swarm mode: set by orchestrator per worker
 */

// =============================================================================
// TYPES
// =============================================================================

export interface VerificationCriteria {
  /** Tests that must be run (e.g., pytest test paths) */
  requiredTests?: string[];
  /** Must have edited at least one file */
  requireFileChanges?: boolean;
  /** Max nudges before giving up and allowing completion */
  maxAttempts?: number;
}

export interface VerificationState {
  /** Tests that have been detected as run */
  testsRun: Set<string>;
  /** Whether any test passed */
  anyTestPassed: boolean;
  /** Whether file changes were made */
  hasFileChanges: boolean;
  /** Number of verification nudges already sent */
  nudgeCount: number;
}

export interface VerificationCheckResult {
  /** Whether verification criteria are satisfied */
  satisfied: boolean;
  /** If not satisfied, a nudge message to inject */
  nudge?: string;
  /** If max attempts exceeded, allow anyway */
  forceAllow: boolean;
  /** What's still missing */
  missing: string[];
}

// =============================================================================
// VERIFICATION GATE
// =============================================================================

export class VerificationGate {
  private criteria: VerificationCriteria;
  private state: VerificationState;

  constructor(criteria: VerificationCriteria) {
    this.criteria = {
      requiredTests: criteria.requiredTests,
      requireFileChanges: criteria.requireFileChanges ?? false,
      maxAttempts: criteria.maxAttempts ?? 2,
    };

    this.state = {
      testsRun: new Set(),
      anyTestPassed: false,
      hasFileChanges: false,
      nudgeCount: 0,
    };
  }

  /**
   * Record that a bash command was executed.
   * Detects test execution from command patterns and output.
   */
  recordBashExecution(command: string, output: string, exitCode: number | null): void {
    // Detect pytest/test runs
    const isTestRun = /pytest|python\s+-m\s+pytest/.test(command);
    if (isTestRun) {
      this.state.testsRun.add(command);
      if (exitCode === 0) {
        this.state.anyTestPassed = true;
      }

      // Check if specific required tests were run
      if (this.criteria.requiredTests) {
        for (const req of this.criteria.requiredTests) {
          if (command.includes(req) || output.includes(req)) {
            this.state.testsRun.add(req);
          }
        }
      }
    }
  }

  /**
   * Record that a file was modified.
   */
  recordFileChange(): void {
    this.state.hasFileChanges = true;
  }

  /**
   * Check if the agent can complete.
   * Returns satisfied=true if criteria are met, or a nudge message if not.
   */
  check(): VerificationCheckResult {
    const missing: string[] = [];

    // Check file changes
    if (this.criteria.requireFileChanges && !this.state.hasFileChanges) {
      missing.push('No file changes made');
    }

    // Check required tests
    if (this.criteria.requiredTests && this.criteria.requiredTests.length > 0) {
      if (this.state.testsRun.size === 0) {
        missing.push('Required tests have not been run');
      } else if (!this.state.anyTestPassed) {
        missing.push('Tests ran but none passed');
      }
    }

    // All criteria met
    if (missing.length === 0) {
      return { satisfied: true, forceAllow: false, missing: [] };
    }

    // Max nudges exceeded - allow anyway
    if (this.state.nudgeCount >= (this.criteria.maxAttempts ?? 2)) {
      return { satisfied: false, forceAllow: true, missing };
    }

    // Generate nudge
    this.state.nudgeCount++;
    const nudge = this.buildNudge(missing);

    return { satisfied: false, forceAllow: false, nudge, missing };
  }

  /**
   * Get the current verification state.
   */
  getState(): {
    testsRun: number;
    anyTestPassed: boolean;
    hasFileChanges: boolean;
    nudgeCount: number;
    maxAttempts: number;
  } {
    return {
      testsRun: this.state.testsRun.size,
      anyTestPassed: this.state.anyTestPassed,
      hasFileChanges: this.state.hasFileChanges,
      nudgeCount: this.state.nudgeCount,
      maxAttempts: this.criteria.maxAttempts ?? 2,
    };
  }

  /**
   * Reset the gate state (for reuse).
   */
  reset(): void {
    this.state = {
      testsRun: new Set(),
      anyTestPassed: false,
      hasFileChanges: false,
      nudgeCount: 0,
    };
  }

  // ---------------------------------------------------------------------------
  // PRIVATE
  // ---------------------------------------------------------------------------

  private buildNudge(missing: string[]): string {
    const parts = ['[System] Verification incomplete:'];
    for (const m of missing) {
      parts.push(`- ${m}`);
    }

    if (this.criteria.requiredTests && this.criteria.requiredTests.length > 0) {
      const testCmd = `python -m pytest ${this.criteria.requiredTests.join(' ')} -xvs`;
      parts.push(`\nRun the required tests now: \`${testCmd}\``);
    }

    parts.push('Do NOT finish until verification is complete.');
    return parts.join('\n');
  }
}

// =============================================================================
// FACTORY
// =============================================================================

/**
 * Create a verification gate from criteria.
 * Returns null if no criteria provided (gate disabled).
 */
export function createVerificationGate(
  criteria?: VerificationCriteria | null,
): VerificationGate | null {
  if (!criteria) return null;
  // Only create if there's something to verify
  if (!criteria.requiredTests?.length && !criteria.requireFileChanges) return null;
  return new VerificationGate(criteria);
}
