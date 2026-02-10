/**
 * Thinking/Reflection Strategy
 *
 * Generates thinking directives that guide LLMs to use their
 * internal reasoning (extended thinking) for better planning,
 * evaluation, and self-assessment.
 *
 * Following Anthropic's multi-agent research pattern:
 * thinking is controlled through prompt engineering, not code mechanics.
 */

import type { ComplexityTier } from './complexity-classifier.js';

// =============================================================================
// TYPES
// =============================================================================

export interface ThinkingDirective {
  /** What the model should think about before acting */
  preActionPrompt?: string;
  /** What the model should evaluate after tool results */
  postToolPrompt?: string;
  /** Quality assessment prompt before returning results */
  qualityCheckPrompt?: string;
}

export interface ThinkingConfig {
  /** Enable pre-task planning in thinking */
  enablePreTaskPlanning: boolean;
  /** Enable post-tool evaluation in thinking */
  enablePostToolEvaluation: boolean;
  /** Enable quality self-assessment */
  enableQualityAssessment: boolean;
  /** Minimum complexity tier for thinking activation */
  minComplexityTier: ComplexityTier;
}

// =============================================================================
// CONSTANTS
// =============================================================================

const DEFAULT_CONFIG: ThinkingConfig = {
  enablePreTaskPlanning: true,
  enablePostToolEvaluation: true,
  enableQualityAssessment: true,
  minComplexityTier: 'medium',
};

/**
 * Complexity tier ordering for comparison.
 */
const TIER_ORDER: Record<ComplexityTier, number> = {
  simple: 0,
  medium: 1,
  complex: 2,
  deep_research: 3,
};

// =============================================================================
// DIRECTIVE GENERATORS
// =============================================================================

/**
 * Generate thinking directives based on complexity and config.
 */
export function generateThinkingDirectives(
  complexityTier: ComplexityTier,
  config?: Partial<ThinkingConfig>,
): ThinkingDirective {
  const cfg = { ...DEFAULT_CONFIG, ...config };

  // Check if thinking should be activated for this complexity level
  if (TIER_ORDER[complexityTier] < TIER_ORDER[cfg.minComplexityTier]) {
    return {}; // No thinking directives for simple tasks
  }

  const directive: ThinkingDirective = {};

  if (cfg.enablePreTaskPlanning) {
    directive.preActionPrompt = getPreActionPrompt(complexityTier);
  }

  if (cfg.enablePostToolEvaluation) {
    directive.postToolPrompt = getPostToolPrompt(complexityTier);
  }

  if (cfg.enableQualityAssessment) {
    directive.qualityCheckPrompt = getQualityCheckPrompt(complexityTier);
  }

  return directive;
}

function getPreActionPrompt(tier: ComplexityTier): string {
  if (tier === 'deep_research' || tier === 'complex') {
    return `Before taking any action, use your thinking to:
1. Assess which tools are most relevant for this task
2. Determine the optimal sequence of operations
3. If complex, plan which subagents to spawn and what each should do
4. Identify potential pitfalls or dependencies between subtasks
5. Decide whether to explore more or act on what you know

Then proceed with your plan.`;
  }

  return `Before acting, briefly assess in your thinking:
1. What tools are most relevant for this task?
2. What is the most efficient approach?
3. Are there dependencies between steps?

Then proceed.`;
}

function getPostToolPrompt(_tier: ComplexityTier): string {
  return `After receiving tool results, evaluate in your thinking:
- Did the tool calls return useful information?
- Is the information sufficient or do I need more?
- Should I change approach based on what I learned?
- Are there any errors or unexpected results to address?`;
}

function getQualityCheckPrompt(_tier: ComplexityTier): string {
  return `Before returning your final answer, evaluate in your thinking:
1. Did I address all aspects of the objective?
2. Is my output complete and in the correct format?
3. Have I met all success criteria?
4. Are there any gaps or issues I should flag?`;
}

// =============================================================================
// SYSTEM PROMPT INTEGRATION
// =============================================================================

/**
 * Generate thinking-related system prompt additions.
 * Injected into buildMessages() for complex tasks.
 */
export function getThinkingSystemPrompt(
  complexityTier: ComplexityTier,
  config?: Partial<ThinkingConfig>,
): string | null {
  const directive = generateThinkingDirectives(complexityTier, config);

  if (!directive.preActionPrompt && !directive.postToolPrompt) {
    return null;
  }

  const parts: string[] = ['## Thinking Guidelines'];

  if (directive.preActionPrompt) {
    parts.push(`### Before Acting\n${directive.preActionPrompt}`);
  }

  if (directive.postToolPrompt) {
    parts.push(`### After Tool Results\n${directive.postToolPrompt}`);
  }

  return parts.join('\n\n');
}

/**
 * Generate quality self-assessment prompt for subagents.
 * Added to subagent constraints before they return.
 */
export function getSubagentQualityPrompt(): string {
  return `Before returning your final result, evaluate your work:
1. Did you fully address the objective given to you?
2. Is your output in the expected format?
3. Did you stay within scope (not doing more or less than asked)?
4. Are there any unresolved issues or gaps to flag to the parent?

If you find gaps, note them clearly in your response.`;
}

/**
 * Create a thinking strategy manager.
 */
export function createThinkingStrategy(
  config?: Partial<ThinkingConfig>,
): {
  generateDirectives: (tier: ComplexityTier) => ThinkingDirective;
  getSystemPrompt: (tier: ComplexityTier) => string | null;
  getSubagentPrompt: () => string;
} {
  return {
    generateDirectives: (tier) => generateThinkingDirectives(tier, config),
    getSystemPrompt: (tier) => getThinkingSystemPrompt(tier, config),
    getSubagentPrompt: getSubagentQualityPrompt,
  };
}
