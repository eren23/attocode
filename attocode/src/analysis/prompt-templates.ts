/**
 * Analysis Prompt Templates
 *
 * Structured prompts for LLM analysis of trace data.
 */

import type { TraceSummary } from '../tracing/types.js';

/**
 * Available analysis templates.
 */
export type AnalysisTemplate =
  | 'efficiencyAudit'
  | 'issueInvestigation'
  | 'comparisonAnalysis'
  | 'rootCauseAnalysis';

/**
 * Prompt context for analysis.
 */
export interface PromptContext {
  /** Primary trace summary */
  summary: TraceSummary;
  /** Comparison trace summary (for comparison analysis) */
  baselineSummary?: TraceSummary;
  /** Specific issue to investigate */
  issueId?: string;
  /** Additional context */
  context?: string;
}

/**
 * Analysis prompt templates.
 */
export const PROMPT_TEMPLATES: Record<AnalysisTemplate, (ctx: PromptContext) => string> = {
  /**
   * Efficiency audit - broad analysis of session efficiency.
   */
  efficiencyAudit: (ctx: PromptContext) =>
    `
You are an expert at analyzing AI agent execution traces. Analyze this trace summary and provide an efficiency audit.

## Trace Summary
\`\`\`json
${JSON.stringify(ctx.summary, null, 2)}
\`\`\`

## Analysis Instructions

1. **Efficiency Score (0-100)**: Calculate based on:
   - Iteration count vs task complexity
   - Cache hit rate
   - Tool call redundancy
   - Error rate

2. **Issues**: Identify problems with severity levels:
   - critical: Prevents completion or causes failure
   - high: Significant inefficiency (>50% waste)
   - medium: Moderate inefficiency (20-50% waste)
   - low: Minor optimization opportunity

3. **Recommendations**: Provide actionable improvements:
   - Priority (1-5, 1 is highest)
   - Expected improvement
   - Effort level (low/medium/high)

4. **Code Locations**: Map issues to specific code locations when possible

## Response Format

Respond with a JSON object matching this schema:
\`\`\`typescript
{
  efficiencyScore: number; // 0-100
  issues: Array<{
    id: string;
    severity: 'low' | 'medium' | 'high' | 'critical';
    category: string;
    description: string;
    evidence: string;
    suggestedFix?: string;
    codeLocations?: string[];
  }>;
  recommendations: Array<{
    priority: number;
    recommendation: string;
    expectedImprovement: string;
    effort: 'low' | 'medium' | 'high';
  }>;
}
\`\`\`
`.trim(),

  /**
   * Issue investigation - deep dive into a specific issue.
   */
  issueInvestigation: (ctx: PromptContext) =>
    `
You are an expert at debugging AI agent behavior. Investigate this specific issue in the trace.

## Issue ID: ${ctx.issueId || 'unknown'}

## Trace Summary
\`\`\`json
${JSON.stringify(ctx.summary, null, 2)}
\`\`\`

${ctx.context ? `## Additional Context\n${ctx.context}` : ''}

## Investigation Instructions

1. **Identify the root cause**: What directly caused this issue?
2. **Trace the causal chain**: What led to the root cause?
3. **Find contributing factors**: What made this worse?
4. **Propose fixes**: How to prevent this in the future?

## Response Format

Respond with a JSON object:
\`\`\`typescript
{
  issueId: string;
  rootCause: string;
  causalChain: string[];
  contributingFactors: string[];
  proposedFixes: Array<{
    fix: string;
    effort: 'low' | 'medium' | 'high';
    impact: 'low' | 'medium' | 'high';
    codeLocations: string[];
  }>;
}
\`\`\`
`.trim(),

  /**
   * Comparison analysis - compare two sessions.
   */
  comparisonAnalysis: (ctx: PromptContext) =>
    `
You are an expert at comparing AI agent execution patterns. Compare these two trace sessions.

## Baseline Session
\`\`\`json
${JSON.stringify(ctx.baselineSummary, null, 2)}
\`\`\`

## Comparison Session
\`\`\`json
${JSON.stringify(ctx.summary, null, 2)}
\`\`\`

## Analysis Instructions

1. **Identify regressions**: What got worse?
2. **Identify improvements**: What got better?
3. **Explain changes**: Why did metrics change?
4. **Assess overall**: Is this a net improvement?

## Response Format

Respond with a JSON object:
\`\`\`typescript
{
  regressions: string[];
  improvements: string[];
  neutral: string[];
  overallAssessment: 'improved' | 'regressed' | 'mixed' | 'similar';
  explanation: string;
  recommendations: string[];
}
\`\`\`
`.trim(),

  /**
   * Root cause analysis - five whys approach.
   */
  rootCauseAnalysis: (ctx: PromptContext) =>
    `
You are an expert at root cause analysis. Use the Five Whys technique to analyze this trace failure.

## Trace Summary
\`\`\`json
${JSON.stringify(ctx.summary, null, 2)}
\`\`\`

## Problem Statement
${ctx.context || 'The session did not complete efficiently or failed.'}

## Analysis Instructions

Apply the Five Whys technique:
1. Start with the observed problem
2. Ask "Why?" at each level
3. Continue until you reach the root cause
4. Identify the ultimate cause and fix

## Response Format

Respond with a JSON object:
\`\`\`typescript
{
  problem: string;
  whyChain: Array<{
    why: string;
    answer: string;
  }>;
  rootCause: string;
  suggestedFix: string;
  preventionStrategy: string;
}
\`\`\`
`.trim(),
};

/**
 * Generate an analysis prompt.
 */
export function generateAnalysisPrompt(template: AnalysisTemplate, context: PromptContext): string {
  const generator = PROMPT_TEMPLATES[template];
  if (!generator) {
    throw new Error(`Unknown analysis template: ${template}`);
  }
  return generator(context);
}

/**
 * Get available templates.
 */
export function getAvailableTemplates(): AnalysisTemplate[] {
  return Object.keys(PROMPT_TEMPLATES) as AnalysisTemplate[];
}
