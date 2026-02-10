/**
 * Self-Improvement Protocol
 *
 * Diagnoses tool call failures, proposes description improvements,
 * and connects to the existing FailureTracker and LearningStore
 * for cross-session persistence.
 *
 * Key features:
 * - Tool failure diagnosis (why did this fail?)
 * - Improved arguments suggestion (how to fix the call)
 * - Tool description improvements (better docs for the LLM)
 * - Success pattern tracking
 */

import type { LearningStore } from './learning-store.js';
import type { FailureCategory as ExternalFailureCategory } from '../tricks/failure-evidence.js';

// =============================================================================
// TYPES
// =============================================================================

export interface ToolCallDiagnosis {
  /** Tool that was called */
  toolName: string;
  /** Original arguments that failed */
  originalArgs: Record<string, unknown>;
  /** The error message */
  error: string;
  /** Why it failed */
  diagnosis: string;
  /** How to fix the call */
  suggestedFix: string;
  /** Fixed arguments (if determinable) */
  improvedArgs?: Record<string, unknown>;
  /** Better tool description (if applicable) */
  descriptionImprovement?: string;
  /** Error category */
  category: FailureCategory;
}

export type FailureCategory =
  | 'wrong_args'       // Arguments were malformed or wrong type
  | 'missing_args'     // Required arguments were missing
  | 'file_not_found'   // Target file doesn't exist
  | 'permission'       // Permission denied
  | 'timeout'          // Operation timed out
  | 'syntax_error'     // Command syntax error
  | 'state_error'      // System not in expected state
  | 'unknown';         // Can't determine cause

export interface SelfImprovementConfig {
  /** Enable tool call diagnosis (default: true) */
  enableDiagnosis: boolean;
  /** Enable description improvement proposals (default: false) */
  enableDescriptionImprovement: boolean;
  /** Maximum diagnoses to cache (default: 50) */
  maxDiagnosisCache: number;
}

export interface SuccessPattern {
  toolName: string;
  argPattern: Record<string, string>; // Key -> type/pattern
  context: string;
  count: number;
}

// =============================================================================
// CONSTANTS
// =============================================================================

const DEFAULT_CONFIG: SelfImprovementConfig = {
  enableDiagnosis: true,
  enableDescriptionImprovement: false,
  maxDiagnosisCache: 50,
};

/**
 * Common error patterns and their diagnoses.
 */
const ERROR_PATTERNS: Array<{
  pattern: RegExp;
  category: FailureCategory;
  diagnosis: string;
  fix: string;
}> = [
  {
    pattern: /ENOENT|no such file|file not found|does not exist/i,
    category: 'file_not_found',
    diagnosis: 'The target file or directory does not exist',
    fix: 'Use glob or list_files to verify the path before accessing it',
  },
  {
    pattern: /EACCES|permission denied|not permitted/i,
    category: 'permission',
    diagnosis: 'Insufficient permissions to perform this operation',
    fix: 'Check file permissions or try a different approach',
  },
  {
    pattern: /timeout|timed out|ETIMEDOUT/i,
    category: 'timeout',
    diagnosis: 'The operation timed out',
    fix: 'Try with a shorter command or increase timeout',
  },
  {
    pattern: /syntax error|unexpected token|parse error/i,
    category: 'syntax_error',
    diagnosis: 'The command or arguments contain a syntax error',
    fix: 'Check command syntax and argument formatting',
  },
  {
    pattern: /required|missing|undefined is not/i,
    category: 'missing_args',
    diagnosis: 'One or more required arguments were not provided',
    fix: 'Review the tool schema and provide all required arguments',
  },
  {
    pattern: /invalid|not a valid|type error|expected.*got/i,
    category: 'wrong_args',
    diagnosis: 'The arguments were of the wrong type or format',
    fix: 'Check the argument types against the tool schema',
  },
  {
    pattern: /not found in file|no match|unique match/i,
    category: 'state_error',
    diagnosis: 'The expected content was not found (file may have changed)',
    fix: 'Re-read the file to get current content before editing',
  },
];

// =============================================================================
// PROTOCOL
// =============================================================================

export class SelfImprovementProtocol {
  private config: SelfImprovementConfig;
  private learningStore: LearningStore | null;
  private diagnosisCache: Map<string, ToolCallDiagnosis> = new Map();
  private successPatterns: Map<string, SuccessPattern> = new Map();
  private failureCounts: Map<string, number> = new Map();

  constructor(
    config?: Partial<SelfImprovementConfig>,
    learningStore?: LearningStore | null,
  ) {
    this.config = { ...DEFAULT_CONFIG, ...config };
    this.learningStore = learningStore ?? null;
  }

  /**
   * Diagnose why a tool call failed.
   * Uses error pattern matching for fast diagnosis.
   */
  diagnoseToolFailure(
    toolName: string,
    args: Record<string, unknown>,
    error: string,
    _toolDescription?: string,
  ): ToolCallDiagnosis {
    // Track failure count
    const failKey = toolName;
    const count = (this.failureCounts.get(failKey) ?? 0) + 1;
    this.failureCounts.set(failKey, count);

    // Match against known patterns
    let category: FailureCategory = 'unknown';
    let diagnosis = 'Unable to determine the exact cause of failure';
    let suggestedFix = 'Try a different approach or tool';

    for (const pattern of ERROR_PATTERNS) {
      if (pattern.pattern.test(error)) {
        category = pattern.category;
        diagnosis = pattern.diagnosis;
        suggestedFix = pattern.fix;
        break;
      }
    }

    // Build improved args for specific categories
    let improvedArgs: Record<string, unknown> | undefined;
    if (category === 'file_not_found' && args.path) {
      // Suggest using glob to find the file
      suggestedFix = `File "${args.path}" not found. Use glob to search for similar files.`;
    }
    if (category === 'state_error' && toolName === 'edit_file') {
      suggestedFix = 'Re-read the file to get current content, then retry the edit.';
    }

    const result: ToolCallDiagnosis = {
      toolName,
      originalArgs: args,
      error,
      diagnosis,
      suggestedFix,
      improvedArgs,
      category,
    };

    // Cache the diagnosis
    const cacheKey = `${toolName}:${error.slice(0, 100)}`;
    this.diagnosisCache.set(cacheKey, result);
    if (this.diagnosisCache.size > this.config.maxDiagnosisCache) {
      // Remove oldest entries
      const keys = [...this.diagnosisCache.keys()];
      for (let i = 0; i < 10; i++) {
        this.diagnosisCache.delete(keys[i]);
      }
    }

    // Persist to learning store for cross-session learning
    if (this.learningStore && count >= 3) {
      this.persistFailureLearning(toolName, diagnosis, suggestedFix);
    }

    return result;
  }

  /**
   * Record a successful tool call pattern.
   */
  recordSuccess(toolName: string, args: Record<string, unknown>, context: string): void {
    const key = `${toolName}:${Object.keys(args).sort().join(',')}`;
    const existing = this.successPatterns.get(key);

    if (existing) {
      existing.count++;
    } else {
      this.successPatterns.set(key, {
        toolName,
        argPattern: Object.fromEntries(
          Object.entries(args).map(([k, v]) => [k, typeof v]),
        ),
        context,
        count: 1,
      });
    }

    // Reset failure count on success
    this.failureCounts.set(toolName, 0);
  }

  /**
   * Get failure count for a tool.
   */
  getFailureCount(toolName: string): number {
    return this.failureCounts.get(toolName) ?? 0;
  }

  /**
   * Check if a tool has been failing repeatedly (3+ times).
   */
  isRepeatedlyFailing(toolName: string): boolean {
    return (this.failureCounts.get(toolName) ?? 0) >= 3;
  }

  /**
   * Get a diagnosis-enhanced error message for the LLM.
   * Includes the diagnosis and suggested fix alongside the error.
   */
  enhanceErrorMessage(toolName: string, error: string, args: Record<string, unknown>): string {
    if (!this.config.enableDiagnosis) return error;

    const diagnosis = this.diagnoseToolFailure(toolName, args, error);

    const parts = [error];
    if (diagnosis.diagnosis !== 'Unable to determine the exact cause of failure') {
      parts.push(`\n[Diagnosis: ${diagnosis.diagnosis}]`);
      parts.push(`[Suggested fix: ${diagnosis.suggestedFix}]`);
    }

    if (this.isRepeatedlyFailing(toolName)) {
      parts.push(`\n[Warning: "${toolName}" has failed ${this.getFailureCount(toolName)} times. Consider using a different tool or approach.]`);
    }

    return parts.join('');
  }

  /**
   * Get success patterns for a tool (useful for prompt context).
   */
  getSuccessPatterns(toolName: string): SuccessPattern[] {
    return [...this.successPatterns.values()].filter(p => p.toolName === toolName);
  }

  /**
   * Persist a failure learning to the learning store.
   */
  private persistFailureLearning(
    toolName: string,
    diagnosis: string,
    fix: string,
  ): void {
    try {
      this.learningStore?.proposeLearning({
        type: 'best_practice',
        description: `Tool "${toolName}" failure pattern: ${diagnosis}`,
        details: `Fix: ${fix}`,
        categories: ['runtime' as ExternalFailureCategory],
        actions: [toolName],
      });
    } catch {
      // Learning store errors are not critical
    }
  }
}

/**
 * Create a self-improvement protocol.
 */
export function createSelfImprovementProtocol(
  config?: Partial<SelfImprovementConfig>,
  learningStore?: LearningStore | null,
): SelfImprovementProtocol {
  return new SelfImprovementProtocol(config, learningStore);
}
