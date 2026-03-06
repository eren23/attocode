/**
 * Phase Tracker - Phase transitions and nudge generation for the economics system.
 *
 * Extracted from economics.ts (Phase 3b restructuring).
 *
 * Handles:
 * - Phase state management (exploring -> planning -> acting -> verifying)
 * - Phase transition triggers
 * - Exploration saturation detection
 * - Test outcome parsing (pass/fail tracking)
 * - Nudge prompt generation for exploration budget, verification reserve
 */

import type {
  PhaseState,
  EconomicsTuning,
  EconomicsEvent,
  PhaseBudgetConfig,
} from './economics.js';

// =============================================================================
// PROMPT TEMPLATES
// =============================================================================

/**
 * Exploration saturation prompt - gentle nudge to start making edits.
 */
export const EXPLORATION_NUDGE_PROMPT = (filesRead: number, iterations: number) =>
  `[System] You've read ${filesRead} files across ${iterations} iterations. If you understand the issue:
- Make the code changes now
- Run tests to verify
If you're still gathering context, briefly explain what you're looking for.`;

/**
 * Phase budget exploration exceeded prompt.
 */
export const EXPLORATION_BUDGET_EXCEEDED_PROMPT = (pct: number) =>
  `[System] You've spent ${pct}% of your iterations in exploration. Start making edits NOW.
Do not read more files. Use what you know to make the fix.`;

/**
 * Phase budget verification reserve prompt.
 */
export const VERIFICATION_RESERVE_PROMPT = `[System] You are running low on iterations. Run your tests NOW to verify your changes.
Do not make more edits until you've confirmed whether the current fix works.`;

// =============================================================================
// PHASE TRACKER CLASS
// =============================================================================

/**
 * Callback for emitting economics events from the phase tracker.
 */
export type PhaseEventEmitter = (event: EconomicsEvent) => void;

/**
 * PhaseTracker manages execution phase state and transitions.
 *
 * Phases: exploring -> planning -> acting -> verifying
 *
 * Provides:
 * - Automatic phase transitions based on tool calls (first edit -> acting, tests after edits -> verifying)
 * - Exploration saturation detection (too many files read without edits)
 * - Test outcome tracking (consecutive failures, test-fix cycles)
 * - Bash failure cascade tracking
 * - Summary loop detection (consecutive text-only turns)
 */
export class PhaseTracker {
  private state: PhaseState;
  private tuning: EconomicsTuning | undefined;
  private emit: PhaseEventEmitter;

  constructor(tuning: EconomicsTuning | undefined, emit: PhaseEventEmitter) {
    this.tuning = tuning;
    this.emit = emit;
    this.state = PhaseTracker.createInitialState();
  }

  /**
   * Create the initial phase state.
   */
  static createInitialState(): PhaseState {
    return {
      phase: 'exploring',
      explorationStartIteration: 0,
      uniqueFilesRead: new Set(),
      uniqueSearches: new Set(),
      filesModified: new Set(),
      testsRun: 0,
      shouldTransition: false,
      iterationsInPhase: 0,
      recentNewFiles: 0,
      lastTestPassed: null,
      consecutiveTestFailures: 0,
      inTestFixCycle: false,
      consecutiveBashFailures: 0,
      consecutiveTextOnlyTurns: 0,
    };
  }

  /**
   * Record a text-only turn (LLM response with no tool calls).
   * Increments the consecutive text-only turn counter for summary-loop detection.
   */
  recordTextOnlyTurn(): void {
    this.state.consecutiveTextOnlyTurns++;
  }

  /**
   * Called on every tool call to reset text-only counter and update phase iteration.
   */
  onToolCall(): void {
    this.state.consecutiveTextOnlyTurns = 0;
    this.state.iterationsInPhase++;

    // Reset recentNewFiles counter every 3 iterations for diminishing returns check
    if (this.state.iterationsInPhase % 3 === 0) {
      this.state.recentNewFiles = 0;
    }
  }

  /**
   * Track a file read operation and return whether it was a new file.
   */
  trackFileRead(path: string): boolean {
    const isNew = !this.state.uniqueFilesRead.has(path);
    this.state.uniqueFilesRead.add(path);
    if (isNew) {
      this.state.recentNewFiles++;
    }
    return isNew;
  }

  /**
   * Track a search operation.
   */
  trackSearch(query: string): void {
    this.state.uniqueSearches.add(query);
  }

  /**
   * Track a file modification and trigger phase transition if needed.
   */
  trackFileModified(path: string): void {
    this.state.filesModified.add(path);
    // Transition to acting phase when first edit is made
    if (this.state.phase === 'exploring' || this.state.phase === 'planning') {
      this.transitionPhase('acting', 'First file edit made');
    }
  }

  /**
   * Track a bash command execution result.
   */
  trackBashResult(command: string, success: boolean, output: string): void {
    // Track consecutive bash failures
    if (!success) {
      this.state.consecutiveBashFailures++;
    } else {
      this.state.consecutiveBashFailures = 0;
    }

    // Detect test runs and track outcomes
    if (
      command.includes('test') ||
      command.includes('pytest') ||
      command.includes('npm test') ||
      command.includes('jest')
    ) {
      this.state.testsRun++;
      // Transition to verifying phase when tests are run after edits
      if (this.state.phase === 'acting' && this.state.filesModified.size > 0) {
        this.transitionPhase('verifying', 'Tests run after edits');
      }
      if (output) {
        this.parseTestOutcome(command, output);
      }
    }
  }

  /**
   * Check for exploration saturation (reading too many files without action).
   */
  checkExplorationSaturation(): void {
    const { phase, uniqueFilesRead, iterationsInPhase, recentNewFiles, filesModified } = this.state;

    // Only check during exploration phase
    if (phase !== 'exploring') {
      this.state.shouldTransition = false;
      return;
    }

    // After N+ unique files without edits, suggest transition (configurable, default: 10)
    const fileThreshold = this.tuning?.explorationFileThreshold ?? 10;
    if (uniqueFilesRead.size >= fileThreshold && filesModified.size === 0) {
      this.state.shouldTransition = true;
      this.emit({
        type: 'exploration.saturation',
        filesRead: uniqueFilesRead.size,
        iterations: iterationsInPhase,
      });
      return;
    }

    // After N+ iterations in exploration with diminishing returns (configurable, default: 15)
    const iterThreshold = this.tuning?.explorationIterThreshold ?? 15;
    if (iterationsInPhase >= iterThreshold && recentNewFiles < 2 && filesModified.size === 0) {
      this.state.shouldTransition = true;
      this.emit({
        type: 'exploration.saturation',
        filesRead: uniqueFilesRead.size,
        iterations: iterationsInPhase,
      });
      return;
    }

    this.state.shouldTransition = false;
  }

  /**
   * Get a serializable snapshot of the phase state (for getPhaseState() API).
   */
  getSnapshot(): {
    phase: string;
    uniqueFilesRead: number;
    uniqueSearches: number;
    filesModified: number;
    testsRun: number;
    shouldTransition: boolean;
    iterationsInPhase: number;
    lastTestPassed: boolean | null;
    consecutiveTestFailures: number;
    inTestFixCycle: boolean;
    consecutiveBashFailures: number;
  } {
    return {
      phase: this.state.phase,
      uniqueFilesRead: this.state.uniqueFilesRead.size,
      uniqueSearches: this.state.uniqueSearches.size,
      filesModified: this.state.filesModified.size,
      testsRun: this.state.testsRun,
      shouldTransition: this.state.shouldTransition,
      iterationsInPhase: this.state.iterationsInPhase,
      lastTestPassed: this.state.lastTestPassed,
      consecutiveTestFailures: this.state.consecutiveTestFailures,
      inTestFixCycle: this.state.inTestFixCycle,
      consecutiveBashFailures: this.state.consecutiveBashFailures,
    };
  }

  /**
   * Direct access to the raw phase state (for internal economics manager use).
   */
  get rawState(): PhaseState {
    return this.state;
  }

  /**
   * Reset the phase tracker to initial state.
   */
  reset(): void {
    this.state = PhaseTracker.createInitialState();
  }

  // ---------------------------------------------------------------------------
  // PRIVATE METHODS
  // ---------------------------------------------------------------------------

  /**
   * Transition to a new phase.
   */
  private transitionPhase(newPhase: PhaseState['phase'], reason: string): void {
    const oldPhase = this.state.phase;
    if (oldPhase === newPhase) return;

    this.emit({
      type: 'phase.transition',
      from: oldPhase,
      to: newPhase,
      reason,
    });

    this.state.phase = newPhase;
    this.state.iterationsInPhase = 0;
    this.state.recentNewFiles = 0;

    if (newPhase === 'exploring') {
      // explorationStartIteration is set by the caller (economics manager)
      // since it knows the current iteration count
    }
  }

  /**
   * Parse test outcome from bash command output.
   * Updates test tracking fields.
   */
  private parseTestOutcome(_command: string, output: string): void {
    if (!output) return;

    // Detect pass/fail from pytest-style output
    const hasPassed = /(\d+)\s+passed/.test(output) || output.includes('PASSED');
    const hasFailed =
      /(\d+)\s+failed/.test(output) || output.includes('FAILED') || output.includes('ERROR');

    if (hasFailed && !hasPassed) {
      // Pure failure
      this.state.lastTestPassed = false;
      this.state.consecutiveTestFailures++;
      this.state.inTestFixCycle = true;
    } else if (hasPassed && !hasFailed) {
      // Pure pass
      this.state.lastTestPassed = true;
      this.state.consecutiveTestFailures = 0;
      this.state.inTestFixCycle = false;
    } else if (hasPassed && hasFailed) {
      // Mixed - some passed, some failed
      this.state.lastTestPassed = false;
      this.state.consecutiveTestFailures++;
      this.state.inTestFixCycle = true;
    }
    // If no clear signal, don't update
  }
}
