/**
 * Lesson 16: Reflector
 *
 * Generates reflection prompts and processes reflection responses.
 * This is the core component for agent self-evaluation.
 */

import type {
  Reflector,
  ReflectionResult,
  ReflectionContext,
  ReflectionIssue,
  ReflectionCriteria,
  IssueType,
  DEFAULT_CRITERIA,
} from './types.js';

// =============================================================================
// REFLECTION PROMPT TEMPLATES
// =============================================================================

/**
 * Templates for generating reflection prompts.
 *
 * USER CONTRIBUTION OPPORTUNITY:
 * The reflection prompt design significantly impacts reflection quality.
 * You could customize these templates for:
 * - Different domains (code, writing, analysis)
 * - Different strictness levels
 * - Specific quality criteria
 */
export const REFLECTION_TEMPLATES = {
  /**
   * Standard reflection prompt.
   */
  standard: (goal: string, output: string, context?: ReflectionContext): string => `
You are a critical evaluator. Your task is to assess whether the following output
successfully achieves the stated goal.

## Goal
${goal}

## Output to Evaluate
${output}

${context?.requirements?.length ? `## Requirements
${context.requirements.map((r) => `- ${r}`).join('\n')}` : ''}

${context?.previousAttempts?.length ? `## Previous Attempts
This is attempt #${context.previousAttempts.length + 1}. Previous issues:
${context.previousAttempts.map((a, i) => `Attempt ${i + 1}: ${a.reflection.critique}`).join('\n')}` : ''}

## Your Task
Evaluate the output against the goal. Be thorough but fair.

Respond in the following JSON format:
{
  "satisfied": boolean,
  "critique": "detailed critique",
  "suggestions": ["suggestion 1", "suggestion 2"],
  "confidence": 0.0-1.0,
  "issues": [
    {
      "type": "incomplete|incorrect|unclear|inefficient|inconsistent|off_topic|style|security|edge_case",
      "description": "what's wrong",
      "severity": "low|medium|high|critical",
      "suggestedFix": "how to fix"
    }
  ],
  "strengths": ["what was done well"]
}
`.trim(),

  /**
   * Code-specific reflection prompt.
   */
  code: (goal: string, output: string, context?: ReflectionContext): string => `
You are a senior code reviewer. Evaluate the following code against the requirements.

## Requirements
${goal}

## Code to Review
\`\`\`
${output}
\`\`\`

## Evaluation Criteria
1. **Correctness**: Does it work as intended?
2. **Completeness**: Are all requirements addressed?
3. **Code Quality**: Is it readable, maintainable, well-structured?
4. **Edge Cases**: Are edge cases handled?
5. **Security**: Are there any security concerns?
6. **Efficiency**: Is it reasonably efficient?

Respond in JSON format:
{
  "satisfied": boolean,
  "critique": "detailed code review",
  "suggestions": ["specific improvement suggestions"],
  "confidence": 0.0-1.0,
  "issues": [{"type": "...", "description": "...", "severity": "...", "location": "line/function", "suggestedFix": "..."}],
  "strengths": ["positive aspects"]
}
`.trim(),

  /**
   * Writing-specific reflection prompt.
   */
  writing: (goal: string, output: string, context?: ReflectionContext): string => `
You are an editor reviewing written content. Evaluate the following text.

## Goal
${goal}

## Text to Review
${output}

## Evaluation Criteria
1. **Clarity**: Is it easy to understand?
2. **Completeness**: Does it fully address the goal?
3. **Structure**: Is it well-organized?
4. **Tone**: Is the tone appropriate?
5. **Accuracy**: Is the information accurate?

Respond in JSON format:
{
  "satisfied": boolean,
  "critique": "detailed editorial feedback",
  "suggestions": ["specific improvements"],
  "confidence": 0.0-1.0,
  "issues": [{"type": "...", "description": "...", "severity": "..."}],
  "strengths": ["positive aspects"]
}
`.trim(),
};

// =============================================================================
// SIMPLE REFLECTOR
// =============================================================================

/**
 * A simple pattern-based reflector for demonstration.
 * In production, this would call an LLM.
 */
export class SimpleReflector implements Reflector {
  private criteria: ReflectionCriteria;

  constructor(criteria: Partial<ReflectionCriteria> = {}) {
    this.criteria = {
      checkCompleteness: true,
      checkCorrectness: true,
      checkCodeQuality: true,
      checkClarity: true,
      checkEdgeCases: false,
      customCriteria: [],
      confidenceThreshold: 0.7,
      ...criteria,
    };
  }

  /**
   * Reflect on output using pattern matching.
   */
  async reflect(
    goal: string,
    output: string,
    context?: ReflectionContext
  ): Promise<ReflectionResult> {
    const issues: ReflectionIssue[] = [];
    const strengths: string[] = [];

    // Check completeness
    if (this.criteria.checkCompleteness) {
      const completenessIssues = this.checkCompleteness(goal, output);
      issues.push(...completenessIssues);
      if (completenessIssues.length === 0) {
        strengths.push('Output appears complete');
      }
    }

    // Check code quality (if output looks like code)
    if (this.criteria.checkCodeQuality && this.looksLikeCode(output)) {
      const codeIssues = this.checkCodeQuality(output);
      issues.push(...codeIssues);
      if (codeIssues.length === 0) {
        strengths.push('Code follows good practices');
      }
    }

    // Check clarity
    if (this.criteria.checkClarity) {
      const clarityIssues = this.checkClarity(output);
      issues.push(...clarityIssues);
      if (clarityIssues.length === 0) {
        strengths.push('Output is clear and readable');
      }
    }

    // Check custom criteria
    for (const criterion of this.criteria.customCriteria) {
      const customIssues = this.checkCustomCriterion(criterion, output);
      issues.push(...customIssues);
    }

    // Calculate confidence based on issues
    const confidence = this.calculateConfidence(issues);
    const satisfied = confidence >= this.criteria.confidenceThreshold &&
      !issues.some((i) => i.severity === 'critical');

    // Generate critique
    const critique = this.generateCritique(issues, strengths);

    // Generate suggestions
    const suggestions = await this.suggest(goal, output, issues);

    return {
      satisfied,
      critique,
      suggestions,
      confidence,
      issues,
      strengths,
    };
  }

  /**
   * Generate improvement suggestions.
   */
  async suggest(
    goal: string,
    output: string,
    issues: ReflectionIssue[]
  ): Promise<string[]> {
    const suggestions: string[] = [];

    for (const issue of issues) {
      if (issue.suggestedFix) {
        suggestions.push(issue.suggestedFix);
      } else {
        // Generate generic suggestion based on issue type
        suggestions.push(this.generateSuggestion(issue));
      }
    }

    return suggestions.slice(0, 5); // Limit to top 5 suggestions
  }

  // ===========================================================================
  // CHECKING METHODS
  // ===========================================================================

  /**
   * Check if output is complete.
   */
  private checkCompleteness(goal: string, output: string): ReflectionIssue[] {
    const issues: ReflectionIssue[] = [];
    const goalWords = goal.toLowerCase().split(/\s+/);

    // Check for common incompleteness indicators
    if (output.includes('TODO') || output.includes('FIXME')) {
      issues.push({
        type: 'incomplete',
        description: 'Output contains TODO or FIXME markers',
        severity: 'medium',
        suggestedFix: 'Complete all TODO items',
      });
    }

    if (output.includes('...') && output.length < 100) {
      issues.push({
        type: 'incomplete',
        description: 'Output appears truncated',
        severity: 'high',
        suggestedFix: 'Provide complete output',
      });
    }

    // Check if key terms from goal appear in output
    const keyTerms = goalWords.filter((w) => w.length > 4);
    const outputLower = output.toLowerCase();
    const missingTerms = keyTerms.filter((t) => !outputLower.includes(t));

    if (missingTerms.length > keyTerms.length / 2) {
      issues.push({
        type: 'incomplete',
        description: 'Output may not fully address the goal',
        severity: 'medium',
        suggestedFix: `Ensure output addresses: ${missingTerms.slice(0, 3).join(', ')}`,
      });
    }

    return issues;
  }

  /**
   * Check code quality.
   */
  private checkCodeQuality(output: string): ReflectionIssue[] {
    const issues: ReflectionIssue[] = [];

    // Check for common code smells
    if (/console\.log\([^)]+\)/g.test(output)) {
      issues.push({
        type: 'style',
        description: 'Contains console.log statements',
        severity: 'low',
        suggestedFix: 'Remove or replace with proper logging',
      });
    }

    if (/any/g.test(output) && /typescript|\.ts/i.test(output)) {
      issues.push({
        type: 'style',
        description: 'Uses "any" type in TypeScript',
        severity: 'medium',
        suggestedFix: 'Use proper typing instead of any',
      });
    }

    // Check for missing error handling
    if (output.includes('async') && !output.includes('try') && !output.includes('catch')) {
      issues.push({
        type: 'edge_case',
        description: 'Async code without error handling',
        severity: 'medium',
        suggestedFix: 'Add try/catch for error handling',
      });
    }

    // Check for hardcoded values
    const hardcodedStrings = output.match(/"[^"]{20,}"/g);
    if (hardcodedStrings && hardcodedStrings.length > 3) {
      issues.push({
        type: 'inefficient',
        description: 'Multiple hardcoded strings detected',
        severity: 'low',
        suggestedFix: 'Consider using constants or configuration',
      });
    }

    return issues;
  }

  /**
   * Check clarity.
   */
  private checkClarity(output: string): ReflectionIssue[] {
    const issues: ReflectionIssue[] = [];

    // Check for very long lines
    const lines = output.split('\n');
    const longLines = lines.filter((l) => l.length > 120);
    if (longLines.length > 5) {
      issues.push({
        type: 'unclear',
        description: 'Many lines exceed 120 characters',
        severity: 'low',
        suggestedFix: 'Break long lines for readability',
      });
    }

    // Check for lack of structure
    if (output.length > 500 && !output.includes('\n\n')) {
      issues.push({
        type: 'unclear',
        description: 'Large block of text without paragraphs',
        severity: 'medium',
        suggestedFix: 'Add paragraph breaks for readability',
      });
    }

    // Check for comments in code
    if (this.looksLikeCode(output) && !output.includes('//') && !output.includes('/*')) {
      if (output.length > 200) {
        issues.push({
          type: 'unclear',
          description: 'Code lacks comments',
          severity: 'low',
          suggestedFix: 'Add comments to explain complex logic',
        });
      }
    }

    return issues;
  }

  /**
   * Check custom criterion.
   */
  private checkCustomCriterion(criterion: string, output: string): ReflectionIssue[] {
    const issues: ReflectionIssue[] = [];
    const criterionLower = criterion.toLowerCase();

    // Simple keyword checking for custom criteria
    if (criterionLower.includes('must include')) {
      const requiredTerm = criterionLower.split('must include')[1]?.trim();
      if (requiredTerm && !output.toLowerCase().includes(requiredTerm)) {
        issues.push({
          type: 'incomplete',
          description: `Missing required element: ${requiredTerm}`,
          severity: 'high',
          suggestedFix: `Include ${requiredTerm} in the output`,
        });
      }
    }

    return issues;
  }

  // ===========================================================================
  // HELPER METHODS
  // ===========================================================================

  /**
   * Check if output looks like code.
   */
  private looksLikeCode(output: string): boolean {
    const codeIndicators = [
      /function\s+\w+/,
      /const\s+\w+\s*=/,
      /let\s+\w+\s*=/,
      /class\s+\w+/,
      /import\s+.*from/,
      /export\s+/,
      /=>\s*{/,
      /\)\s*{/,
    ];

    return codeIndicators.some((pattern) => pattern.test(output));
  }

  /**
   * Calculate confidence based on issues.
   */
  private calculateConfidence(issues: ReflectionIssue[]): number {
    let confidence = 1.0;

    for (const issue of issues) {
      switch (issue.severity) {
        case 'critical':
          confidence -= 0.3;
          break;
        case 'high':
          confidence -= 0.15;
          break;
        case 'medium':
          confidence -= 0.08;
          break;
        case 'low':
          confidence -= 0.03;
          break;
      }
    }

    return Math.max(0, Math.min(1, confidence));
  }

  /**
   * Generate critique from issues and strengths.
   */
  private generateCritique(issues: ReflectionIssue[], strengths: string[]): string {
    const parts: string[] = [];

    if (strengths.length > 0) {
      parts.push(`Strengths: ${strengths.join('. ')}.`);
    }

    if (issues.length === 0) {
      parts.push('No significant issues found.');
    } else {
      const criticalIssues = issues.filter((i) => i.severity === 'critical' || i.severity === 'high');
      const minorIssues = issues.filter((i) => i.severity === 'medium' || i.severity === 'low');

      if (criticalIssues.length > 0) {
        parts.push(`Critical issues: ${criticalIssues.map((i) => i.description).join('; ')}.`);
      }

      if (minorIssues.length > 0) {
        parts.push(`Minor issues: ${minorIssues.map((i) => i.description).join('; ')}.`);
      }
    }

    return parts.join(' ');
  }

  /**
   * Generate suggestion from issue.
   */
  private generateSuggestion(issue: ReflectionIssue): string {
    const typeToAction: Record<IssueType, string> = {
      incomplete: 'Complete the missing parts',
      incorrect: 'Fix the error',
      unclear: 'Improve clarity',
      inefficient: 'Optimize the implementation',
      inconsistent: 'Resolve the inconsistency',
      off_topic: 'Refocus on the original goal',
      style: 'Improve code style',
      security: 'Address security concern',
      edge_case: 'Handle the edge case',
    };

    return `${typeToAction[issue.type]}: ${issue.description}`;
  }
}

// =============================================================================
// EXPORTS
// =============================================================================

export const defaultReflector = new SimpleReflector();
