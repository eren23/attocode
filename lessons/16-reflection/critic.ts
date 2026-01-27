/**
 * Lesson 16: Critic
 *
 * Provides structured critique and scoring of output.
 * Separates critique (detailed feedback) from reflection (goal satisfaction).
 */

import type {
  Critic,
  CritiqueResult,
  QualityScore,
  ReflectionCriteria,
  ReflectionIssue,
  IssueType,
  DEFAULT_CRITERIA,
} from './types.js';

// =============================================================================
// QUALITY RUBRICS
// =============================================================================

/**
 * Rubrics for scoring different quality dimensions.
 */
export const QUALITY_RUBRICS = {
  completeness: {
    name: 'Completeness',
    description: 'Does the output address all requirements?',
    levels: {
      100: 'All requirements fully addressed with thoroughness',
      80: 'All requirements addressed',
      60: 'Most requirements addressed',
      40: 'Some requirements addressed',
      20: 'Few requirements addressed',
      0: 'Requirements not addressed',
    },
  },

  correctness: {
    name: 'Correctness',
    description: 'Is the output accurate and error-free?',
    levels: {
      100: 'Completely correct with no errors',
      80: 'Correct with minor issues',
      60: 'Mostly correct with some errors',
      40: 'Partially correct',
      20: 'Significant errors present',
      0: 'Fundamentally incorrect',
    },
  },

  clarity: {
    name: 'Clarity',
    description: 'Is the output easy to understand?',
    levels: {
      100: 'Exceptionally clear and well-organized',
      80: 'Clear and readable',
      60: 'Understandable with some effort',
      40: 'Somewhat confusing',
      20: 'Difficult to understand',
      0: 'Incomprehensible',
    },
  },

  efficiency: {
    name: 'Efficiency',
    description: 'Is the implementation optimal?',
    levels: {
      100: 'Highly optimized and elegant',
      80: 'Efficient implementation',
      60: 'Reasonably efficient',
      40: 'Some inefficiencies',
      20: 'Significant inefficiencies',
      0: 'Very inefficient',
    },
  },

  style: {
    name: 'Style',
    description: 'Does it follow best practices and conventions?',
    levels: {
      100: 'Exemplary style and conventions',
      80: 'Good style adherence',
      60: 'Acceptable style',
      40: 'Some style issues',
      20: 'Poor style',
      0: 'No attention to style',
    },
  },
};

// =============================================================================
// OUTPUT CRITIC
// =============================================================================

/**
 * Critiques output across multiple quality dimensions.
 */
export class OutputCritic implements Critic {
  /**
   * Critique output against criteria.
   */
  async critique(
    output: string,
    criteria: ReflectionCriteria
  ): Promise<CritiqueResult> {
    const issues: ReflectionIssue[] = [];
    const positives: string[] = [];

    // Run each enabled check
    if (criteria.checkCompleteness) {
      const result = this.assessCompleteness(output);
      issues.push(...result.issues);
      positives.push(...result.positives);
    }

    if (criteria.checkCorrectness) {
      const result = this.assessCorrectness(output);
      issues.push(...result.issues);
      positives.push(...result.positives);
    }

    if (criteria.checkCodeQuality) {
      const result = this.assessCodeQuality(output);
      issues.push(...result.issues);
      positives.push(...result.positives);
    }

    if (criteria.checkClarity) {
      const result = this.assessClarity(output);
      issues.push(...result.issues);
      positives.push(...result.positives);
    }

    if (criteria.checkEdgeCases) {
      const result = this.assessEdgeCases(output);
      issues.push(...result.issues);
      positives.push(...result.positives);
    }

    // Calculate overall score
    const score = await this.score(output);
    const assessment = this.scoreToAssessment(score.overall);

    return {
      assessment,
      issues,
      positives,
      score: score.overall,
    };
  }

  /**
   * Score output on multiple dimensions.
   */
  async score(output: string): Promise<QualityScore> {
    const dimensions = {
      completeness: this.scoreCompleteness(output),
      correctness: this.scoreCorrectness(output),
      clarity: this.scoreClarity(output),
      efficiency: this.scoreEfficiency(output),
      style: this.scoreStyle(output),
    };

    // Calculate weighted average
    const weights = {
      completeness: 0.25,
      correctness: 0.30,
      clarity: 0.20,
      efficiency: 0.15,
      style: 0.10,
    };

    const overall = Object.entries(dimensions).reduce((sum, [key, value]) => {
      return sum + value * weights[key as keyof typeof weights];
    }, 0);

    return {
      overall: Math.round(overall),
      dimensions,
    };
  }

  // ===========================================================================
  // ASSESSMENT METHODS
  // ===========================================================================

  /**
   * Assess completeness.
   */
  private assessCompleteness(output: string): { issues: ReflectionIssue[]; positives: string[] } {
    const issues: ReflectionIssue[] = [];
    const positives: string[] = [];

    // Check for TODO markers
    const todoCount = (output.match(/TODO|FIXME|XXX/g) || []).length;
    if (todoCount > 0) {
      issues.push({
        type: 'incomplete',
        description: `Contains ${todoCount} TODO/FIXME markers`,
        severity: todoCount > 3 ? 'high' : 'medium',
      });
    } else {
      positives.push('No TODO markers present');
    }

    // Check for placeholder text
    if (/\[.*?\]|<.*?>/.test(output) && output.length > 100) {
      const placeholders = output.match(/\[.*?\]|<[A-Z_]+>/g);
      if (placeholders && placeholders.length > 2) {
        issues.push({
          type: 'incomplete',
          description: 'Contains placeholder text',
          severity: 'medium',
        });
      }
    }

    // Check for minimum content
    if (output.trim().length < 50) {
      issues.push({
        type: 'incomplete',
        description: 'Output appears too short',
        severity: 'high',
      });
    } else if (output.trim().length > 200) {
      positives.push('Substantial content provided');
    }

    return { issues, positives };
  }

  /**
   * Assess correctness.
   */
  private assessCorrectness(output: string): { issues: ReflectionIssue[]; positives: string[] } {
    const issues: ReflectionIssue[] = [];
    const positives: string[] = [];

    // Check for syntax errors in code
    if (this.looksLikeCode(output)) {
      const syntaxIssues = this.checkSyntax(output);
      issues.push(...syntaxIssues);

      if (syntaxIssues.length === 0) {
        positives.push('No obvious syntax errors');
      }
    }

    // Check for contradictions (simple heuristic)
    if (output.includes(' not ') && output.includes(' always ')) {
      // Very basic check - in production would use more sophisticated analysis
    }

    return { issues, positives };
  }

  /**
   * Assess code quality.
   */
  private assessCodeQuality(output: string): { issues: ReflectionIssue[]; positives: string[] } {
    const issues: ReflectionIssue[] = [];
    const positives: string[] = [];

    if (!this.looksLikeCode(output)) {
      return { issues, positives };
    }

    // Check for documentation
    if (output.includes('/**') || output.includes('///')) {
      positives.push('Contains documentation');
    } else if (output.length > 300) {
      issues.push({
        type: 'style',
        description: 'Missing documentation',
        severity: 'low',
      });
    }

    // Check for type annotations (TypeScript)
    if (output.includes('function') || output.includes('const')) {
      if (output.includes(': ') && !output.includes(': any')) {
        positives.push('Uses proper type annotations');
      }
    }

    // Check for error handling
    if (output.includes('async') || output.includes('Promise')) {
      if (output.includes('catch') || output.includes('try')) {
        positives.push('Includes error handling');
      } else {
        issues.push({
          type: 'edge_case',
          description: 'Async code without error handling',
          severity: 'medium',
        });
      }
    }

    // Check for magic numbers
    const magicNumbers = output.match(/[^\w]([2-9]|[1-9]\d+)[^\w]/g);
    if (magicNumbers && magicNumbers.length > 5) {
      issues.push({
        type: 'style',
        description: 'Multiple magic numbers detected',
        severity: 'low',
      });
    }

    return { issues, positives };
  }

  /**
   * Assess clarity.
   */
  private assessClarity(output: string): { issues: ReflectionIssue[]; positives: string[] } {
    const issues: ReflectionIssue[] = [];
    const positives: string[] = [];

    const lines = output.split('\n');

    // Check line lengths
    const longLines = lines.filter((l) => l.length > 100).length;
    if (longLines > 10) {
      issues.push({
        type: 'unclear',
        description: `${longLines} lines exceed 100 characters`,
        severity: 'low',
      });
    }

    // Check for structure
    const emptyLineCount = lines.filter((l) => l.trim() === '').length;
    if (output.length > 500 && emptyLineCount > 2) {
      positives.push('Well-structured with proper spacing');
    } else if (output.length > 500 && emptyLineCount <= 2) {
      issues.push({
        type: 'unclear',
        description: 'Large block without paragraph breaks',
        severity: 'medium',
      });
    }

    // Check naming (for code)
    if (this.looksLikeCode(output)) {
      const hasDescriptiveNames = /[a-z][A-Za-z]{10,}/.test(output);
      if (hasDescriptiveNames) {
        positives.push('Uses descriptive naming');
      }
    }

    return { issues, positives };
  }

  /**
   * Assess edge case handling.
   */
  private assessEdgeCases(output: string): { issues: ReflectionIssue[]; positives: string[] } {
    const issues: ReflectionIssue[] = [];
    const positives: string[] = [];

    if (!this.looksLikeCode(output)) {
      return { issues, positives };
    }

    // Check for null/undefined handling
    if (output.includes('null') || output.includes('undefined')) {
      if (output.includes('??') || output.includes('?.') || output.includes('!= null')) {
        positives.push('Handles null/undefined cases');
      }
    }

    // Check for empty array/string handling
    if (output.includes('.length')) {
      if (output.includes('.length === 0') || output.includes('.length > 0')) {
        positives.push('Checks for empty collections');
      } else {
        issues.push({
          type: 'edge_case',
          description: 'May not handle empty collections',
          severity: 'low',
        });
      }
    }

    // Check for boundary conditions
    if (output.includes('for') || output.includes('while')) {
      if (output.includes('<') && output.includes('<=')) {
        // Has both strict and non-strict comparisons - might be intentional
      }
    }

    return { issues, positives };
  }

  // ===========================================================================
  // SCORING METHODS
  // ===========================================================================

  /**
   * Score completeness dimension.
   */
  private scoreCompleteness(output: string): number {
    let score = 80; // Start optimistic

    // Penalize TODOs
    const todoCount = (output.match(/TODO|FIXME|XXX/g) || []).length;
    score -= todoCount * 10;

    // Penalize short output
    if (output.length < 50) score -= 30;
    else if (output.length < 100) score -= 15;

    // Reward substantial content
    if (output.length > 500) score += 10;

    return Math.max(0, Math.min(100, score));
  }

  /**
   * Score correctness dimension.
   */
  private scoreCorrectness(output: string): number {
    let score = 90; // Start optimistic

    if (this.looksLikeCode(output)) {
      const syntaxIssues = this.checkSyntax(output);
      score -= syntaxIssues.length * 15;
    }

    return Math.max(0, Math.min(100, score));
  }

  /**
   * Score clarity dimension.
   */
  private scoreClarity(output: string): number {
    let score = 80;

    const lines = output.split('\n');

    // Penalize long lines
    const longLines = lines.filter((l) => l.length > 100).length;
    score -= Math.min(20, longLines * 2);

    // Reward good structure
    const emptyLineCount = lines.filter((l) => l.trim() === '').length;
    if (emptyLineCount > 2 && output.length > 300) score += 10;

    // Reward comments in code
    if (this.looksLikeCode(output)) {
      if (output.includes('//') || output.includes('/*')) score += 5;
    }

    return Math.max(0, Math.min(100, score));
  }

  /**
   * Score efficiency dimension.
   */
  private scoreEfficiency(output: string): number {
    let score = 75; // Neutral start

    if (!this.looksLikeCode(output)) {
      return score;
    }

    // Check for nested loops (potential O(n²))
    const nestedLoops = output.match(/for.*\{[^}]*for/g);
    if (nestedLoops) score -= nestedLoops.length * 10;

    // Check for reasonable function size
    const functions = output.match(/function|=>/g) || [];
    if (functions.length > 0) {
      const avgSize = output.length / functions.length;
      if (avgSize > 500) score -= 10; // Functions too long
      if (avgSize < 200) score += 10; // Well-decomposed
    }

    return Math.max(0, Math.min(100, score));
  }

  /**
   * Score style dimension.
   */
  private scoreStyle(output: string): number {
    let score = 70;

    if (!this.looksLikeCode(output)) {
      return score;
    }

    // Reward consistent indentation
    const indents = output.match(/^\s+/gm) || [];
    const indentSizes = new Set(indents.map((i) => i.length % 2));
    if (indentSizes.size <= 1) score += 15;

    // Reward documentation
    if (output.includes('/**')) score += 10;

    // Penalize console.log
    const consoleLogs = (output.match(/console\.log/g) || []).length;
    score -= consoleLogs * 5;

    return Math.max(0, Math.min(100, score));
  }

  // ===========================================================================
  // HELPER METHODS
  // ===========================================================================

  /**
   * Convert score to assessment label.
   */
  private scoreToAssessment(score: number): CritiqueResult['assessment'] {
    if (score >= 90) return 'excellent';
    if (score >= 75) return 'good';
    if (score >= 60) return 'acceptable';
    if (score >= 40) return 'needs_work';
    return 'poor';
  }

  /**
   * Check if output looks like code.
   */
  private looksLikeCode(output: string): boolean {
    const codeIndicators = [
      /function\s+\w+/,
      /const\s+\w+\s*=/,
      /class\s+\w+/,
      /import\s+.*from/,
      /=>\s*[{(]/,
    ];
    return codeIndicators.some((p) => p.test(output));
  }

  /**
   * Check for syntax issues.
   */
  private checkSyntax(output: string): ReflectionIssue[] {
    const issues: ReflectionIssue[] = [];

    // Check bracket balance
    const openBrackets = (output.match(/[{[(]/g) || []).length;
    const closeBrackets = (output.match(/[}\])]/g) || []).length;
    if (openBrackets !== closeBrackets) {
      issues.push({
        type: 'incorrect',
        description: 'Unbalanced brackets',
        severity: 'high',
      });
    }

    // Check for common syntax errors
    if (output.includes(';;')) {
      issues.push({
        type: 'incorrect',
        description: 'Double semicolon detected',
        severity: 'low',
      });
    }

    return issues;
  }
}

// =============================================================================
// EXPORTS
// =============================================================================

export const defaultCritic = new OutputCritic();
