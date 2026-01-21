/**
 * Lesson 16: Self-Reflection & Critique Types
 *
 * Type definitions for agent self-reflection and output improvement.
 */

// =============================================================================
// REFLECTION TYPES
// =============================================================================

/**
 * Result of a reflection on an output.
 */
export interface ReflectionResult {
  /** Whether the output satisfies the goal */
  satisfied: boolean;

  /** Detailed critique of the output */
  critique: string;

  /** Specific suggestions for improvement */
  suggestions: string[];

  /** Confidence in the assessment (0-1) */
  confidence: number;

  /** Specific issues identified */
  issues: ReflectionIssue[];

  /** Aspects that were done well */
  strengths: string[];
}

/**
 * A specific issue found during reflection.
 */
export interface ReflectionIssue {
  /** Type of issue */
  type: IssueType;

  /** Description of the issue */
  description: string;

  /** Severity level */
  severity: 'low' | 'medium' | 'high' | 'critical';

  /** Where in the output the issue occurs */
  location?: string;

  /** Suggested fix */
  suggestedFix?: string;
}

/**
 * Types of issues that can be identified.
 */
export type IssueType =
  | 'incomplete'      // Missing required elements
  | 'incorrect'       // Factually wrong or buggy
  | 'unclear'         // Hard to understand
  | 'inefficient'     // Could be done better
  | 'inconsistent'    // Contradicts itself or requirements
  | 'off_topic'       // Doesn't address the goal
  | 'style'           // Style or formatting issues
  | 'security'        // Security concerns
  | 'edge_case';      // Doesn't handle edge cases

// =============================================================================
// REFLECTION CRITERIA
// =============================================================================

/**
 * Criteria for evaluating output.
 */
export interface ReflectionCriteria {
  /** Check if output is complete */
  checkCompleteness: boolean;

  /** Check if output is correct */
  checkCorrectness: boolean;

  /** Check code quality (if applicable) */
  checkCodeQuality: boolean;

  /** Check clarity and readability */
  checkClarity: boolean;

  /** Check for edge cases */
  checkEdgeCases: boolean;

  /** Custom criteria to check */
  customCriteria: string[];

  /** Minimum confidence threshold */
  confidenceThreshold: number;
}

/**
 * Default reflection criteria.
 */
export const DEFAULT_CRITERIA: ReflectionCriteria = {
  checkCompleteness: true,
  checkCorrectness: true,
  checkCodeQuality: true,
  checkClarity: true,
  checkEdgeCases: false,
  customCriteria: [],
  confidenceThreshold: 0.7,
};

// =============================================================================
// REFLECTOR INTERFACE
// =============================================================================

/**
 * Interface for reflecting on output.
 */
export interface Reflector {
  /**
   * Reflect on an output given a goal.
   */
  reflect(
    goal: string,
    output: string,
    context?: ReflectionContext
  ): Promise<ReflectionResult>;

  /**
   * Generate suggestions for improvement.
   */
  suggest(
    goal: string,
    output: string,
    issues: ReflectionIssue[]
  ): Promise<string[]>;
}

/**
 * Context for reflection.
 */
export interface ReflectionContext {
  /** Original requirements or constraints */
  requirements?: string[];

  /** Previous attempts (for learning from mistakes) */
  previousAttempts?: AttemptRecord[];

  /** Domain-specific context */
  domain?: string;

  /** Criteria to use */
  criteria?: Partial<ReflectionCriteria>;
}

/**
 * Record of a previous attempt.
 */
export interface AttemptRecord {
  /** The output that was produced */
  output: string;

  /** Reflection on that output */
  reflection: ReflectionResult;

  /** What was tried differently */
  approach?: string;
}

// =============================================================================
// CRITIC INTERFACE
// =============================================================================

/**
 * Interface for critiquing output.
 */
export interface Critic {
  /**
   * Critique an output against specific criteria.
   */
  critique(
    output: string,
    criteria: ReflectionCriteria
  ): Promise<CritiqueResult>;

  /**
   * Score output on multiple dimensions.
   */
  score(output: string): Promise<QualityScore>;
}

/**
 * Result of a critique.
 */
export interface CritiqueResult {
  /** Overall assessment */
  assessment: 'excellent' | 'good' | 'acceptable' | 'needs_work' | 'poor';

  /** Issues found */
  issues: ReflectionIssue[];

  /** Positive aspects */
  positives: string[];

  /** Overall score (0-100) */
  score: number;
}

/**
 * Quality score across multiple dimensions.
 */
export interface QualityScore {
  /** Overall score (0-100) */
  overall: number;

  /** Breakdown by dimension */
  dimensions: {
    completeness: number;
    correctness: number;
    clarity: number;
    efficiency: number;
    style: number;
  };
}

// =============================================================================
// REFLECTION LOOP TYPES
// =============================================================================

/**
 * Configuration for reflection loop.
 */
export interface ReflectionLoopConfig {
  /** Maximum number of attempts */
  maxAttempts: number;

  /** Stop if confidence exceeds this threshold */
  satisfactionThreshold: number;

  /** Whether to include previous attempts in context */
  includePreviousAttempts: boolean;

  /** Delay between attempts (ms) */
  attemptDelayMs: number;

  /** Criteria for reflection */
  criteria: Partial<ReflectionCriteria>;
}

/**
 * Default loop configuration.
 */
export const DEFAULT_LOOP_CONFIG: ReflectionLoopConfig = {
  maxAttempts: 3,
  satisfactionThreshold: 0.8,
  includePreviousAttempts: true,
  attemptDelayMs: 0,
  criteria: {},
};

/**
 * Result of a reflection loop execution.
 */
export interface ReflectionLoopResult {
  /** Final output */
  output: string;

  /** Number of attempts made */
  attempts: number;

  /** All reflections performed */
  reflections: ReflectionResult[];

  /** Whether the goal was satisfied */
  satisfied: boolean;

  /** Total duration */
  durationMs: number;

  /** Improvement trajectory */
  trajectory: TrajectoryPoint[];
}

/**
 * A point in the improvement trajectory.
 */
export interface TrajectoryPoint {
  /** Attempt number */
  attempt: number;

  /** Confidence at this point */
  confidence: number;

  /** Score at this point */
  score: number;

  /** Key changes made */
  changes: string[];
}

// =============================================================================
// REFLECTION EVENTS
// =============================================================================

/**
 * Events emitted during reflection.
 */
export type ReflectionEvent =
  | { type: 'attempt.started'; attempt: number }
  | { type: 'attempt.completed'; attempt: number; output: string }
  | { type: 'reflection.started'; attempt: number }
  | { type: 'reflection.completed'; attempt: number; result: ReflectionResult }
  | { type: 'improvement.suggested'; suggestions: string[] }
  | { type: 'loop.completed'; result: ReflectionLoopResult }
  | { type: 'loop.terminated'; reason: string };

/**
 * Listener for reflection events.
 */
export type ReflectionEventListener = (event: ReflectionEvent) => void;
