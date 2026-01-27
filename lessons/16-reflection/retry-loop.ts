/**
 * Lesson 16: Reflection Retry Loop
 *
 * Executes tasks with reflection-driven improvement.
 * Retries until output satisfies quality criteria or max attempts reached.
 *
 * USER CONTRIBUTION OPPORTUNITY:
 * The retry decision logic determines when to keep trying.
 * You could implement:
 * - Custom stopping conditions
 * - Adaptive attempt limits
 * - Learning from previous attempts
 */

import type {
  ReflectionLoopConfig,
  ReflectionLoopResult,
  ReflectionResult,
  ReflectionEvent,
  ReflectionEventListener,
  TrajectoryPoint,
  AttemptRecord,
  DEFAULT_LOOP_CONFIG,
} from './types.js';
import { SimpleReflector } from './reflector.js';
import { OutputCritic } from './critic.js';

// =============================================================================
// REFLECTION LOOP
// =============================================================================

/**
 * Executes tasks with reflection-driven improvement.
 */
export class ReflectionLoop {
  private config: ReflectionLoopConfig;
  private reflector: SimpleReflector;
  private critic: OutputCritic;
  private listeners: Set<ReflectionEventListener> = new Set();

  constructor(config: Partial<ReflectionLoopConfig> = {}) {
    this.config = {
      maxAttempts: config.maxAttempts ?? 3,
      satisfactionThreshold: config.satisfactionThreshold ?? 0.8,
      includePreviousAttempts: config.includePreviousAttempts ?? true,
      attemptDelayMs: config.attemptDelayMs ?? 0,
      criteria: config.criteria ?? {},
    };

    this.reflector = new SimpleReflector(this.config.criteria);
    this.critic = new OutputCritic();
  }

  // ===========================================================================
  // MAIN EXECUTION
  // ===========================================================================

  /**
   * Execute a task with reflection-driven improvement.
   *
   * @param task - Function that produces output
   * @param goal - Description of what the output should achieve
   * @param improver - Optional function to improve output based on feedback
   */
  async execute(
    task: (context: TaskContext) => Promise<string>,
    goal: string,
    improver?: OutputImprover
  ): Promise<ReflectionLoopResult> {
    const startTime = performance.now();
    const reflections: ReflectionResult[] = [];
    const trajectory: TrajectoryPoint[] = [];
    const attempts: AttemptRecord[] = [];

    let output = '';
    let attempt = 0;
    let satisfied = false;

    while (attempt < this.config.maxAttempts && !satisfied) {
      attempt++;
      this.emit({ type: 'attempt.started', attempt });

      // Build context with previous attempts
      const context: TaskContext = {
        attempt,
        previousAttempts: this.config.includePreviousAttempts ? attempts : [],
        goal,
      };

      // Execute the task
      try {
        output = await task(context);
      } catch (error) {
        output = `Error: ${error instanceof Error ? error.message : String(error)}`;
      }

      this.emit({ type: 'attempt.completed', attempt, output });

      // Reflect on the output
      this.emit({ type: 'reflection.started', attempt });

      const reflection = await this.reflector.reflect(goal, output, {
        previousAttempts: attempts,
        criteria: this.config.criteria,
      });

      reflections.push(reflection);
      this.emit({ type: 'reflection.completed', attempt, result: reflection });

      // Score for trajectory
      const score = await this.critic.score(output);

      // Record trajectory
      trajectory.push({
        attempt,
        confidence: reflection.confidence,
        score: score.overall,
        changes: reflection.suggestions.slice(0, 3),
      });

      // Record attempt
      attempts.push({
        output,
        reflection,
        approach: attempt > 1 ? `Attempt ${attempt} after applying feedback` : 'Initial attempt',
      });

      // Check if satisfied
      satisfied = this.shouldStop(reflection, attempt);

      // If not satisfied and we have more attempts, try to improve
      if (!satisfied && attempt < this.config.maxAttempts && improver) {
        this.emit({ type: 'improvement.suggested', suggestions: reflection.suggestions });

        // Apply delay if configured
        if (this.config.attemptDelayMs > 0) {
          await this.delay(this.config.attemptDelayMs);
        }

        // The improver can modify the task for the next attempt
        // This is optional - without it, the task function should handle context
      }
    }

    const result: ReflectionLoopResult = {
      output,
      attempts: attempt,
      reflections,
      satisfied,
      durationMs: performance.now() - startTime,
      trajectory,
    };

    this.emit({ type: 'loop.completed', result });

    return result;
  }

  /**
   * Determine if the loop should stop.
   *
   * USER CONTRIBUTION OPPORTUNITY:
   * Implement custom stopping logic here. Consider:
   * - Diminishing returns (confidence not improving)
   * - Critical issues that can't be fixed
   * - Time/resource constraints
   */
  private shouldStop(reflection: ReflectionResult, attempt: number): boolean {
    // Stop if satisfied
    if (reflection.satisfied) {
      return true;
    }

    // Stop if confidence exceeds threshold
    if (reflection.confidence >= this.config.satisfactionThreshold) {
      return true;
    }

    // Stop if critical issues that require human intervention
    const criticalIssues = reflection.issues.filter(
      (i) => i.severity === 'critical' && i.type === 'incorrect'
    );
    if (criticalIssues.length > 0 && attempt > 1) {
      this.emit({
        type: 'loop.terminated',
        reason: 'Critical issues require human intervention',
      });
      return true;
    }

    return false;
  }

  // ===========================================================================
  // CONVENIENCE METHODS
  // ===========================================================================

  /**
   * Execute a simple task (just a string-returning function).
   */
  async executeSimple(
    task: () => Promise<string>,
    goal: string
  ): Promise<ReflectionLoopResult> {
    return this.execute(async () => task(), goal);
  }

  /**
   * Execute with automatic improvement suggestions injected.
   */
  async executeWithFeedback(
    baseTask: (feedback: string[]) => Promise<string>,
    goal: string
  ): Promise<ReflectionLoopResult> {
    let feedbackAccumulator: string[] = [];

    return this.execute(
      async (context) => {
        const output = await baseTask(feedbackAccumulator);

        // Accumulate feedback for next iteration
        if (context.previousAttempts.length > 0) {
          const lastAttempt = context.previousAttempts[context.previousAttempts.length - 1];
          feedbackAccumulator = [
            ...feedbackAccumulator,
            ...lastAttempt.reflection.suggestions,
          ];
        }

        return output;
      },
      goal
    );
  }

  // ===========================================================================
  // ANALYSIS METHODS
  // ===========================================================================

  /**
   * Analyze the improvement trajectory.
   */
  analyzeTrajectory(result: ReflectionLoopResult): TrajectoryAnalysis {
    if (result.trajectory.length === 0) {
      return {
        improved: false,
        totalImprovement: 0,
        avgImprovementPerAttempt: 0,
        convergence: 'none',
        bottleneck: null,
      };
    }

    const scores = result.trajectory.map((t) => t.score);
    const confidences = result.trajectory.map((t) => t.confidence);

    const firstScore = scores[0];
    const lastScore = scores[scores.length - 1];
    const totalImprovement = lastScore - firstScore;

    // Calculate score differences between attempts
    const improvements: number[] = [];
    for (let i = 1; i < scores.length; i++) {
      improvements.push(scores[i] - scores[i - 1]);
    }

    const avgImprovement = improvements.length > 0
      ? improvements.reduce((a, b) => a + b, 0) / improvements.length
      : 0;

    // Determine convergence pattern
    let convergence: 'improving' | 'plateau' | 'declining' | 'oscillating' | 'none' = 'none';
    if (improvements.length >= 2) {
      const allPositive = improvements.every((i) => i > 0);
      const allNegative = improvements.every((i) => i < 0);
      const allSmall = improvements.every((i) => Math.abs(i) < 5);

      if (allPositive) convergence = 'improving';
      else if (allNegative) convergence = 'declining';
      else if (allSmall) convergence = 'plateau';
      else convergence = 'oscillating';
    }

    // Find bottleneck (most common issue type)
    const issueTypes = result.reflections.flatMap((r) => r.issues.map((i) => i.type));
    const typeCounts = new Map<string, number>();
    for (const type of issueTypes) {
      typeCounts.set(type, (typeCounts.get(type) || 0) + 1);
    }

    let bottleneck: string | null = null;
    let maxCount = 0;
    for (const [type, count] of typeCounts) {
      if (count > maxCount) {
        maxCount = count;
        bottleneck = type;
      }
    }

    return {
      improved: totalImprovement > 0,
      totalImprovement,
      avgImprovementPerAttempt: avgImprovement,
      convergence,
      bottleneck,
    };
  }

  // ===========================================================================
  // EVENT HANDLING
  // ===========================================================================

  /**
   * Subscribe to loop events.
   */
  on(listener: ReflectionEventListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /**
   * Emit an event.
   */
  private emit(event: ReflectionEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch (error) {
        console.error('Error in reflection event listener:', error);
      }
    }
  }

  // ===========================================================================
  // UTILITIES
  // ===========================================================================

  /**
   * Delay execution.
   */
  private delay(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }
}

// =============================================================================
// SUPPORTING TYPES
// =============================================================================

/**
 * Context passed to the task function.
 */
export interface TaskContext {
  /** Current attempt number (1-based) */
  attempt: number;

  /** Previous attempts and their reflections */
  previousAttempts: AttemptRecord[];

  /** The goal being pursued */
  goal: string;
}

/**
 * Function that improves output based on feedback.
 */
export type OutputImprover = (
  currentOutput: string,
  feedback: ReflectionResult
) => Promise<string>;

/**
 * Analysis of improvement trajectory.
 */
export interface TrajectoryAnalysis {
  /** Whether score improved overall */
  improved: boolean;

  /** Total score improvement */
  totalImprovement: number;

  /** Average improvement per attempt */
  avgImprovementPerAttempt: number;

  /** Convergence pattern */
  convergence: 'improving' | 'plateau' | 'declining' | 'oscillating' | 'none';

  /** Most common issue type (bottleneck) */
  bottleneck: string | null;
}

// =============================================================================
// FACTORY FUNCTIONS
// =============================================================================

/**
 * Create a reflection loop with sensible defaults.
 */
export function createReflectionLoop(
  options: Partial<ReflectionLoopConfig> = {}
): ReflectionLoop {
  return new ReflectionLoop(options);
}

/**
 * Create a strict reflection loop (higher standards).
 */
export function createStrictLoop(): ReflectionLoop {
  return new ReflectionLoop({
    maxAttempts: 5,
    satisfactionThreshold: 0.9,
    includePreviousAttempts: true,
    criteria: {
      checkCompleteness: true,
      checkCorrectness: true,
      checkCodeQuality: true,
      checkClarity: true,
      checkEdgeCases: true,
      confidenceThreshold: 0.85,
    },
  });
}

/**
 * Create a lenient reflection loop (lower standards).
 */
export function createLenientLoop(): ReflectionLoop {
  return new ReflectionLoop({
    maxAttempts: 2,
    satisfactionThreshold: 0.6,
    includePreviousAttempts: false,
    criteria: {
      checkCompleteness: true,
      checkCorrectness: true,
      checkCodeQuality: false,
      checkClarity: false,
      checkEdgeCases: false,
      confidenceThreshold: 0.5,
    },
  });
}

// =============================================================================
// EXPORTS
// =============================================================================

export const defaultLoop = new ReflectionLoop();
