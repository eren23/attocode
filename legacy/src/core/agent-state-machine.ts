/**
 * Phase 2.2: Agent State Machine
 *
 * Formalizes the phase tracking that previously lived in economics.ts into a
 * proper state machine with typed transitions, event emission, and per-phase
 * metrics. Testable independently of the economics system.
 *
 * Phases:
 * - exploring: Reading files, searching code, understanding the problem
 * - planning: Creating or editing a plan
 * - acting: Writing/editing files, running commands
 * - verifying: Running tests, checking results
 *
 * Valid transitions:
 *   exploring → planning | acting
 *   planning  → acting | exploring
 *   acting    → verifying | exploring
 *   verifying → acting | exploring
 */

// =============================================================================
// TYPES
// =============================================================================

/** Agent execution phases */
export type AgentPhase = 'exploring' | 'planning' | 'acting' | 'verifying';

/** Per-phase metrics snapshot */
export interface PhaseMetrics {
  /** Phase name */
  phase: AgentPhase;
  /** Iterations spent in this phase */
  iterations: number;
  /** Timestamp when phase was entered */
  enteredAt: number;
  /** Duration in ms (0 if still in phase) */
  duration: number;
  /** Unique files read during this phase */
  filesRead: number;
  /** Unique files modified during this phase */
  filesModified: number;
  /** Tool calls made during this phase */
  toolCalls: number;
}

/** Phase transition record */
export interface PhaseTransition {
  from: AgentPhase;
  to: AgentPhase;
  reason: string;
  timestamp: number;
  /** Metrics from the phase we're leaving */
  fromMetrics: PhaseMetrics;
}

/** State machine events */
export type StateMachineEvent =
  | { type: 'phase.changed'; transition: PhaseTransition }
  | { type: 'phase.metrics'; phase: AgentPhase; metrics: PhaseMetrics };

export type StateMachineEventListener = (event: StateMachineEvent) => void;

/** Current phase state (exposed for economics integration) */
export interface PhaseSnapshot {
  phase: AgentPhase;
  iterationsInPhase: number;
  uniqueFilesRead: Set<string>;
  uniqueSearches: Set<string>;
  filesModified: Set<string>;
  testsRun: number;
  shouldTransition: boolean;
  recentNewFiles: number;
  lastTestPassed: boolean | null;
  consecutiveTestFailures: number;
  inTestFixCycle: boolean;
  consecutiveBashFailures: number;
}

// =============================================================================
// VALID TRANSITIONS
// =============================================================================

/**
 * Allowed phase transitions. Each phase lists the phases it can transition to.
 * Invalid transitions are rejected with a warning.
 */
const VALID_TRANSITIONS: Record<AgentPhase, Set<AgentPhase>> = {
  exploring: new Set(['planning', 'acting']),
  planning: new Set(['acting', 'exploring']),
  acting: new Set(['verifying', 'exploring']),
  verifying: new Set(['acting', 'exploring']),
};

// =============================================================================
// AGENT STATE MACHINE
// =============================================================================

export class AgentStateMachine {
  private currentPhase: AgentPhase;
  private phaseEnteredAt: number;
  private phaseIterations = 0;
  private phaseToolCalls = 0;
  private listeners: StateMachineEventListener[] = [];
  private transitions: PhaseTransition[] = [];

  // Per-phase tracking (mirrors economics PhaseState for backward compat)
  private uniqueFilesRead = new Set<string>();
  private uniqueSearches = new Set<string>();
  private filesModified = new Set<string>();
  private testsRun = 0;
  private shouldTransition = false;
  private recentNewFiles = 0;
  private lastTestPassed: boolean | null = null;
  private consecutiveTestFailures = 0;
  private inTestFixCycle = false;
  private consecutiveBashFailures = 0;

  // Accumulated metrics per phase (for history)
  private phaseHistory: PhaseMetrics[] = [];

  // Tuning thresholds
  private explorationFileThreshold: number;
  private explorationIterThreshold: number;

  constructor(options?: {
    initialPhase?: AgentPhase;
    explorationFileThreshold?: number;
    explorationIterThreshold?: number;
  }) {
    this.currentPhase = options?.initialPhase ?? 'exploring';
    this.phaseEnteredAt = Date.now();
    this.explorationFileThreshold = options?.explorationFileThreshold ?? 10;
    this.explorationIterThreshold = options?.explorationIterThreshold ?? 5;
  }

  // ---------------------------------------------------------------------------
  // PUBLIC API
  // ---------------------------------------------------------------------------

  /** Get the current phase */
  getPhase(): AgentPhase {
    return this.currentPhase;
  }

  /** Get a snapshot of the current phase state (backward-compatible with economics) */
  getPhaseSnapshot(): PhaseSnapshot {
    return {
      phase: this.currentPhase,
      iterationsInPhase: this.phaseIterations,
      uniqueFilesRead: new Set(this.uniqueFilesRead),
      uniqueSearches: new Set(this.uniqueSearches),
      filesModified: new Set(this.filesModified),
      testsRun: this.testsRun,
      shouldTransition: this.shouldTransition,
      recentNewFiles: this.recentNewFiles,
      lastTestPassed: this.lastTestPassed,
      consecutiveTestFailures: this.consecutiveTestFailures,
      inTestFixCycle: this.inTestFixCycle,
      consecutiveBashFailures: this.consecutiveBashFailures,
    };
  }

  /** Get metrics for the current phase */
  getCurrentPhaseMetrics(): PhaseMetrics {
    return {
      phase: this.currentPhase,
      iterations: this.phaseIterations,
      enteredAt: this.phaseEnteredAt,
      duration: Date.now() - this.phaseEnteredAt,
      filesRead: this.uniqueFilesRead.size,
      filesModified: this.filesModified.size,
      toolCalls: this.phaseToolCalls,
    };
  }

  /** Get all phase transition history */
  getTransitions(): readonly PhaseTransition[] {
    return this.transitions;
  }

  /** Get accumulated phase history */
  getPhaseHistory(): readonly PhaseMetrics[] {
    return this.phaseHistory;
  }

  /**
   * Attempt a phase transition.
   * Returns true if transition was valid and executed, false if rejected.
   */
  transition(to: AgentPhase, reason: string): boolean {
    if (to === this.currentPhase) return false;

    const validTargets = VALID_TRANSITIONS[this.currentPhase];
    if (!validTargets.has(to)) {
      return false;
    }

    const fromMetrics = this.getCurrentPhaseMetrics();
    fromMetrics.duration = Date.now() - this.phaseEnteredAt;

    const transition: PhaseTransition = {
      from: this.currentPhase,
      to,
      reason,
      timestamp: Date.now(),
      fromMetrics,
    };

    // Record history
    this.phaseHistory.push({ ...fromMetrics });
    this.transitions.push(transition);

    // Reset phase-local counters
    this.currentPhase = to;
    this.phaseEnteredAt = Date.now();
    this.phaseIterations = 0;
    this.phaseToolCalls = 0;
    this.recentNewFiles = 0;
    this.shouldTransition = false;

    // Emit event
    this.emit({ type: 'phase.changed', transition });

    return true;
  }

  /**
   * Record a tool call and update phase state.
   * This is the primary input signal for the state machine.
   */
  recordToolCall(toolName: string, args: Record<string, unknown>, result?: unknown): void {
    this.phaseIterations++;
    this.phaseToolCalls++;

    // Reset recentNewFiles counter every 3 iterations
    if (this.phaseIterations % 3 === 0) {
      this.recentNewFiles = 0;
    }

    // Track file reads
    if (toolName === 'read_file' && args.path) {
      const path = String(args.path);
      const isNew = !this.uniqueFilesRead.has(path);
      this.uniqueFilesRead.add(path);
      if (isNew) this.recentNewFiles++;
    }

    // Track searches
    if (['grep', 'search', 'glob', 'find_files', 'search_files'].includes(toolName)) {
      const query = String(args.pattern || args.query || args.path || '');
      this.uniqueSearches.add(query);
    }

    // Track file modifications → auto-transition to acting
    if (['write_file', 'edit_file'].includes(toolName) && args.path) {
      this.filesModified.add(String(args.path));
      if (this.currentPhase === 'exploring' || this.currentPhase === 'planning') {
        this.transition('acting', 'First file edit made');
      }
    }

    // Track bash commands
    if (toolName === 'bash' && args.command) {
      const command = String(args.command);
      const bashResult = extractBashSuccess(result);

      // Track consecutive bash failures
      if (result !== undefined) {
        if (!bashResult) {
          this.consecutiveBashFailures++;
        } else {
          this.consecutiveBashFailures = 0;
        }
      }

      // Detect test runs
      if (isTestCommand(command)) {
        this.testsRun++;

        // Auto-transition to verifying when tests run after edits
        if (this.currentPhase === 'acting' && this.filesModified.size > 0) {
          this.transition('verifying', 'Tests run after edits');
        }

        // Track test outcomes
        if (result !== undefined) {
          if (bashResult) {
            this.lastTestPassed = true;
            this.consecutiveTestFailures = 0;
            this.inTestFixCycle = false;
          } else {
            this.lastTestPassed = false;
            this.consecutiveTestFailures++;
            // Enter test-fix cycle after 2+ failures
            if (this.consecutiveTestFailures >= 2) {
              this.inTestFixCycle = true;
              // Go back to acting to fix
              if (this.currentPhase === 'verifying') {
                this.transition(
                  'acting',
                  `Test failed ${this.consecutiveTestFailures} times, fixing`,
                );
              }
            }
          }
        }
      }
    }

    // Check exploration saturation
    this.checkExplorationSaturation();
  }

  /** Subscribe to state machine events */
  subscribe(listener: StateMachineEventListener): () => void {
    this.listeners.push(listener);
    return () => {
      const idx = this.listeners.indexOf(listener);
      if (idx >= 0) this.listeners.splice(idx, 1);
    };
  }

  /** Reset state machine to initial state */
  reset(phase?: AgentPhase): void {
    this.currentPhase = phase ?? 'exploring';
    this.phaseEnteredAt = Date.now();
    this.phaseIterations = 0;
    this.phaseToolCalls = 0;
    this.uniqueFilesRead.clear();
    this.uniqueSearches.clear();
    this.filesModified.clear();
    this.testsRun = 0;
    this.shouldTransition = false;
    this.recentNewFiles = 0;
    this.lastTestPassed = null;
    this.consecutiveTestFailures = 0;
    this.inTestFixCycle = false;
    this.consecutiveBashFailures = 0;
    this.transitions = [];
    this.phaseHistory = [];
  }

  // ---------------------------------------------------------------------------
  // PRIVATE
  // ---------------------------------------------------------------------------

  /** Check for exploration saturation (too many reads without action) */
  private checkExplorationSaturation(): void {
    if (this.currentPhase !== 'exploring') {
      this.shouldTransition = false;
      return;
    }

    // After N+ unique files without edits
    if (
      this.uniqueFilesRead.size >= this.explorationFileThreshold &&
      this.filesModified.size === 0
    ) {
      this.shouldTransition = true;
      return;
    }

    // After N+ iterations with diminishing returns
    if (
      this.phaseIterations >= this.explorationIterThreshold &&
      this.recentNewFiles < 2 &&
      this.filesModified.size === 0
    ) {
      this.shouldTransition = true;
      return;
    }

    this.shouldTransition = false;
  }

  private emit(event: StateMachineEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch {
        // Don't let listener errors break the state machine
      }
    }
  }
}

// =============================================================================
// HELPERS
// =============================================================================

/** Check if a bash command is a test command */
function isTestCommand(command: string): boolean {
  return (
    command.includes('test') ||
    command.includes('pytest') ||
    command.includes('npm test') ||
    command.includes('jest')
  );
}

/** Extract success from a bash result (object or string) */
function extractBashSuccess(result: unknown): boolean {
  if (result && typeof result === 'object') {
    return (result as Record<string, unknown>).success !== false;
  }
  return true; // strings and undefined are treated as success
}

// =============================================================================
// FACTORY
// =============================================================================

export function createAgentStateMachine(options?: {
  initialPhase?: AgentPhase;
  explorationFileThreshold?: number;
  explorationIterThreshold?: number;
}): AgentStateMachine {
  return new AgentStateMachine(options);
}
