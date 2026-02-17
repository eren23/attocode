/**
 * Complexity Classifier
 *
 * Heuristic-based task complexity assessment that determines
 * the appropriate execution strategy (agent count, tool budget,
 * swarm mode) without requiring an LLM call.
 *
 * Inspired by Anthropic's multi-agent research system's approach
 * to scaling effort based on task complexity.
 */

// =============================================================================
// TYPES
// =============================================================================

export type ComplexityTier = 'simple' | 'medium' | 'complex' | 'deep_research';

export interface ComplexityAssessment {
  /** Classified complexity tier */
  tier: ComplexityTier;
  /** Confidence in the classification (0-1) */
  confidence: number;
  /** Human-readable reasoning */
  reasoning: string;
  /** Recommended execution parameters */
  recommendation: ExecutionRecommendation;
  /** Signals that contributed to the classification */
  signals: ComplexitySignal[];
}

export interface ExecutionRecommendation {
  /** Number of agents to use */
  agentCount: { min: number; max: number };
  /** Tool calls per agent */
  toolCallsPerAgent: { min: number; max: number };
  /** Whether to use swarm mode */
  useSwarmMode: boolean;
  /** Suggested agent types */
  suggestedAgents: string[];
  /** Budget multiplier relative to standard */
  budgetMultiplier: number;
  /** Whether extended thinking is recommended */
  useExtendedThinking: boolean;
}

export interface ComplexitySignal {
  name: string;
  value: number;
  weight: number;
  description: string;
}

export interface ClassificationContext {
  /** Number of files in the project */
  projectFileCount?: number;
  /** Whether the task references specific files */
  referencesFiles?: boolean;
  /** Previous task in the session (for context) */
  previousTask?: string;
  /** Currently active plan */
  hasActivePlan?: boolean;
}

// =============================================================================
// CONSTANTS
// =============================================================================

/** Keywords that indicate higher complexity */
const COMPLEX_KEYWORDS = [
  // Multi-file operations
  'refactor', 'migrate', 'redesign', 'rewrite', 'overhaul',
  'restructure', 'reorganize', 'rearchitect',
  // Broad scope
  'all files', 'entire', 'codebase', 'every', 'across',
  'comprehensive', 'full audit', 'system-wide',
  // Multi-step
  'first', 'then', 'after that', 'finally', 'step by step',
  'and then', 'once done', 'followed by',
  // Research-heavy
  'investigate', 'analyze', 'audit', 'security review',
  'performance analysis', 'benchmark', 'compare',
];

/** Keywords that indicate simplicity */
const SIMPLE_KEYWORDS = [
  'fix typo', 'rename', 'update version', 'add comment',
  'change color', 'fix import', 'remove unused',
  'what is', 'how does', 'where is', 'explain',
];

/** Dependency indicators (suggest sequential steps) */
const DEPENDENCY_PATTERNS = [
  /first\s.*then/i,
  /after\s.*(?:do|make|create|implement)/i,
  /before\s.*(?:need|must|should)/i,
  /depends?\s+on/i,
  /step\s+\d/i,
  /phase\s+\d/i,
];

/** Tier -> execution recommendation mapping */
const TIER_RECOMMENDATIONS: Record<ComplexityTier, ExecutionRecommendation> = {
  simple: {
    agentCount: { min: 1, max: 1 },
    toolCallsPerAgent: { min: 3, max: 10 },
    useSwarmMode: false,
    suggestedAgents: [],
    budgetMultiplier: 0.5,
    useExtendedThinking: false,
  },
  medium: {
    agentCount: { min: 1, max: 4 },
    toolCallsPerAgent: { min: 10, max: 20 },
    useSwarmMode: false,
    suggestedAgents: ['researcher', 'coder'],
    budgetMultiplier: 1.0,
    useExtendedThinking: false,
  },
  complex: {
    agentCount: { min: 3, max: 8 },
    toolCallsPerAgent: { min: 15, max: 30 },
    useSwarmMode: true,
    suggestedAgents: ['researcher', 'coder', 'reviewer'],
    budgetMultiplier: 2.0,
    useExtendedThinking: true,
  },
  deep_research: {
    agentCount: { min: 5, max: 15 },
    toolCallsPerAgent: { min: 20, max: 50 },
    useSwarmMode: true,
    suggestedAgents: ['researcher', 'coder', 'reviewer', 'architect'],
    budgetMultiplier: 3.0,
    useExtendedThinking: true,
  },
};

// =============================================================================
// CLASSIFIER
// =============================================================================

/**
 * Classify task complexity using heuristic signals.
 * No LLM call needed — fast and deterministic.
 */
export function classifyComplexity(
  task: string,
  context?: ClassificationContext,
): ComplexityAssessment {
  const signals: ComplexitySignal[] = [];
  const taskLower = task.toLowerCase();

  // Signal 1: Task length (proxy for detail/scope)
  const wordCount = task.split(/\s+/).length;
  const lengthScore = wordCount < 10 ? 0 : wordCount < 30 ? 1 : wordCount < 80 ? 2 : 3;
  signals.push({
    name: 'task_length',
    value: lengthScore,
    weight: 0.15,
    description: `${wordCount} words (${lengthScore > 1 ? 'detailed' : 'brief'})`,
  });

  // Signal 2: Complex keyword matches
  const complexMatches = COMPLEX_KEYWORDS.filter(kw => taskLower.includes(kw));
  const complexScore = Math.min(complexMatches.length * 1.5, 4);
  signals.push({
    name: 'complex_keywords',
    value: complexScore,
    weight: 0.25,
    description: complexMatches.length > 0
      ? `Matches: ${complexMatches.slice(0, 3).join(', ')}`
      : 'No complex keywords',
  });

  // Signal 3: Simple keyword matches (reduces score)
  const simpleMatches = SIMPLE_KEYWORDS.filter(kw => taskLower.includes(kw));
  const simpleScore = simpleMatches.length > 0 ? -2 : 0;
  signals.push({
    name: 'simple_keywords',
    value: simpleScore,
    weight: 0.2,
    description: simpleMatches.length > 0
      ? `Simple: ${simpleMatches.slice(0, 2).join(', ')}`
      : 'No simplicity signals',
  });

  // Signal 4: Dependency patterns (suggest multi-step)
  const depMatches = DEPENDENCY_PATTERNS.filter(p => p.test(task));
  const depScore = depMatches.length * 2;
  signals.push({
    name: 'dependency_patterns',
    value: depScore,
    weight: 0.2,
    description: depMatches.length > 0
      ? `${depMatches.length} sequential dependencies detected`
      : 'No dependency chains',
  });

  // Signal 5: Question vs action
  const isQuestion = /^(what|how|where|when|why|which|can|does|is|are)\b/i.test(task.trim());
  const actionScore = isQuestion ? -1 : 1;
  signals.push({
    name: 'question_vs_action',
    value: actionScore,
    weight: 0.1,
    description: isQuestion ? 'Question (likely simpler)' : 'Action request',
  });

  // Signal 6: Multiple file/component references
  const fileRefs = (task.match(/\b\w+\.(ts|tsx|js|jsx|py|rs|go|java|cpp|c|h)\b/g) || []).length;
  const dirRefs = (task.match(/\b(?:src|lib|test|docs|config)\//g) || []).length;
  const scopeScore = Math.min((fileRefs + dirRefs) * 0.5, 3);
  signals.push({
    name: 'scope_indicators',
    value: scopeScore,
    weight: 0.1,
    description: `${fileRefs} file refs, ${dirRefs} dir refs`,
  });

  // Calculate weighted score
  const totalScore = signals.reduce((sum, s) => sum + s.value * s.weight, 0);

  // Determine tier
  let tier: ComplexityTier;
  if (totalScore < 0.5) {
    tier = 'simple';
  } else if (totalScore < 1.5) {
    tier = 'medium';
  } else if (totalScore < 2.5) {
    tier = 'complex';
  } else {
    tier = 'deep_research';
  }

  // Calculate confidence (higher when signals agree)
  const signalVariance = signals.reduce((sum, s) => {
    const normalized = s.value / 4; // Normalize to ~0-1 range
    return sum + Math.abs(normalized - totalScore / 3);
  }, 0) / signals.length;
  const confidence = Math.max(0.3, Math.min(1.0, 1.0 - signalVariance));

  // Build reasoning
  const topSignals = [...signals]
    .sort((a, b) => Math.abs(b.value * b.weight) - Math.abs(a.value * a.weight))
    .slice(0, 3);
  const reasoning = `Classified as ${tier} (score: ${totalScore.toFixed(2)}). ` +
    `Top factors: ${topSignals.map(s => s.description).join('; ')}`;

  return {
    tier,
    confidence,
    reasoning,
    recommendation: TIER_RECOMMENDATIONS[tier],
    signals,
  };
}

/**
 * Generate scaling guidance for injection into the agent's system prompt.
 * This follows Anthropic's pattern of embedding scaling rules directly in prompts.
 */
export function getScalingGuidance(assessment: ComplexityAssessment): string {
  const { tier, recommendation } = assessment;

  const guidelines: Record<ComplexityTier, string> = {
    simple: `## Effort Scaling: SIMPLE TASK
- Handle directly, no subagents needed
- ${recommendation.toolCallsPerAgent.min}-${recommendation.toolCallsPerAgent.max} tool calls maximum
- Respond quickly and concisely
- Do not over-explore the codebase`,

    medium: `## Effort Scaling: MEDIUM TASK
- Consider spawning ${recommendation.agentCount.min}-${recommendation.agentCount.max} subagents for independent subtasks
- Each agent: ${recommendation.toolCallsPerAgent.min}-${recommendation.toolCallsPerAgent.max} tool calls
- Coordinate via blackboard for shared findings
- Balance speed with thoroughness`,

    complex: `## Effort Scaling: COMPLEX TASK
- Spawn ${recommendation.agentCount.min}-${recommendation.agentCount.max} subagents with clear delegation specs
- Use parallel execution where possible
- Quality gate each result before synthesis
- Consider a researcher agent to scope the work first
- Extended thinking recommended for planning`,

    deep_research: `## Effort Scaling: DEEP RESEARCH TASK
- Consider swarm mode for ${recommendation.agentCount.min}+ parallel agents
- Budget for extended exploration and multiple passes
- Use researcher agents to scope before implementation
- Multiple review waves for quality assurance
- Extended thinking strongly recommended`,
  };

  return guidelines[tier];
}

/**
 * Create a complexity classifier with custom thresholds.
 */
export function createComplexityClassifier(config?: {
  simpleThreshold?: number;
  mediumThreshold?: number;
  complexThreshold?: number;
}) {
  const thresholds = {
    simple: config?.simpleThreshold ?? 0.5,
    medium: config?.mediumThreshold ?? 1.5,
    complex: config?.complexThreshold ?? 2.5,
  };

  return {
    classify: (task: string, context?: ClassificationContext) =>
      classifyComplexity(task, context),
    getScalingGuidance,
    thresholds,
  };
}
