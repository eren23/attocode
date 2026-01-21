/**
 * Lesson 22: Capability Matcher
 *
 * Matches tasks to models based on requirements and capabilities.
 * Includes complexity estimation and scoring algorithms.
 */

import type {
  ModelCapability,
  TaskContext,
  ModelRequirements,
  ModelRegistry,
  ModelAlternative,
  TaskType,
} from './types.js';
import { DEFAULT_MODEL_CAPABILITIES } from './types.js';

// =============================================================================
// MODEL REGISTRY IMPLEMENTATION
// =============================================================================

/**
 * Simple in-memory model registry.
 */
export class SimpleModelRegistry implements ModelRegistry {
  private models: Map<string, ModelCapability> = new Map();

  constructor(capabilities: ModelCapability[] = DEFAULT_MODEL_CAPABILITIES) {
    for (const cap of capabilities) {
      this.models.set(cap.model, cap);
    }
  }

  getCapability(model: string): ModelCapability | undefined {
    return this.models.get(model);
  }

  listModels(): ModelCapability[] {
    return Array.from(this.models.values());
  }

  findModels(requirements: ModelRequirements): ModelCapability[] {
    return this.listModels().filter((cap) => this.matchesRequirements(cap, requirements));
  }

  register(capability: ModelCapability): void {
    this.models.set(capability.model, capability);
  }

  update(model: string, updates: Partial<ModelCapability>): void {
    const existing = this.models.get(model);
    if (existing) {
      this.models.set(model, { ...existing, ...updates });
    }
  }

  remove(model: string): boolean {
    return this.models.delete(model);
  }

  private matchesRequirements(cap: ModelCapability, req: ModelRequirements): boolean {
    if (req.minTokens !== undefined && cap.maxTokens < req.minTokens) {
      return false;
    }
    if (req.requiresTools && !cap.supportsTools) {
      return false;
    }
    if (req.requiresVision && !cap.supportsVision) {
      return false;
    }
    if (req.requiresStructuredOutput && !cap.supportsStructuredOutput) {
      return false;
    }
    if (req.maxCostPer1k !== undefined && cap.costPer1kInput > req.maxCostPer1k) {
      return false;
    }
    if (req.maxLatencyMs !== undefined && cap.latencyMs > req.maxLatencyMs) {
      return false;
    }
    if (req.minQualityScore !== undefined && cap.qualityScore < req.minQualityScore) {
      return false;
    }
    if (req.providers && !req.providers.includes(cap.provider)) {
      return false;
    }
    if (req.tags && req.tags.length > 0) {
      if (!req.tags.some((tag) => cap.tags.includes(tag))) {
        return false;
      }
    }
    return true;
  }
}

// =============================================================================
// COMPLEXITY ESTIMATION
// =============================================================================

/**
 * Complexity score factors.
 */
interface ComplexityFactors {
  tokenFactor: number;
  taskTypeFactor: number;
  requirementsFactor: number;
  qualityFactor: number;
}

/**
 * Estimate task complexity.
 *
 * USER CONTRIBUTION OPPORTUNITY:
 * Implement more sophisticated complexity estimation here.
 * Consider:
 * - NLP-based task analysis
 * - Historical data from similar tasks
 * - Domain-specific heuristics
 */
export function estimateComplexity(task: TaskContext): ComplexityFactors {
  // Token factor: larger context = more complex
  const tokenFactor = task.estimatedInputTokens > 10000
    ? 1.0
    : task.estimatedInputTokens > 2000
      ? 0.6
      : 0.3;

  // Task type factor
  const taskTypeComplexity: Record<TaskType, number> = {
    reasoning: 1.0,
    code_generation: 0.9,
    analysis: 0.85,
    code_review: 0.8,
    creative_writing: 0.75,
    summarization: 0.5,
    translation: 0.5,
    extraction: 0.4,
    classification: 0.3,
    chat: 0.3,
    general: 0.5,
  };
  const taskTypeFactor = taskTypeComplexity[task.taskType || 'general'];

  // Requirements factor: more requirements = more complex
  let requirementsFactor = 0.3;
  if (task.requiresTools) requirementsFactor += 0.2;
  if (task.requiresVision) requirementsFactor += 0.2;
  if (task.requiresStructuredOutput) requirementsFactor += 0.1;
  if (task.expectedOutputSize === 'large') requirementsFactor += 0.2;

  // Quality factor
  const qualityMultiplier: Record<string, number> = {
    maximum: 1.0,
    high: 0.8,
    medium: 0.5,
    low: 0.3,
  };
  const qualityFactor = qualityMultiplier[task.qualityRequirement];

  return {
    tokenFactor,
    taskTypeFactor,
    requirementsFactor,
    qualityFactor,
  };
}

/**
 * Calculate overall complexity score (0-1).
 */
export function calculateComplexityScore(task: TaskContext): number {
  const factors = estimateComplexity(task);
  const score =
    factors.tokenFactor * 0.2 +
    factors.taskTypeFactor * 0.3 +
    factors.requirementsFactor * 0.2 +
    factors.qualityFactor * 0.3;
  return Math.min(1, Math.max(0, score));
}

/**
 * Map complexity score to complexity level.
 */
export function getComplexityLevel(score: number): 'simple' | 'moderate' | 'complex' {
  if (score < 0.4) return 'simple';
  if (score < 0.7) return 'moderate';
  return 'complex';
}

// =============================================================================
// CAPABILITY MATCHER
// =============================================================================

/**
 * Model score for ranking.
 */
export interface ModelScore {
  model: string;
  totalScore: number;
  capabilityScore: number;
  costScore: number;
  latencyScore: number;
  qualityScore: number;
  reliabilityScore: number;
  reasons: string[];
}

/**
 * Scoring weights configuration.
 */
export interface ScoringWeights {
  capability: number;
  cost: number;
  latency: number;
  quality: number;
  reliability: number;
}

/**
 * Default weights for different optimization goals.
 */
export const SCORING_PRESETS: Record<string, ScoringWeights> = {
  balanced: {
    capability: 0.25,
    cost: 0.2,
    latency: 0.15,
    quality: 0.25,
    reliability: 0.15,
  },
  quality: {
    capability: 0.2,
    cost: 0.1,
    latency: 0.1,
    quality: 0.45,
    reliability: 0.15,
  },
  cost: {
    capability: 0.2,
    cost: 0.4,
    latency: 0.1,
    quality: 0.15,
    reliability: 0.15,
  },
  speed: {
    capability: 0.2,
    cost: 0.1,
    latency: 0.4,
    quality: 0.15,
    reliability: 0.15,
  },
};

/**
 * Capability matcher for scoring and ranking models.
 */
export class CapabilityMatcher {
  private registry: ModelRegistry;
  private weights: ScoringWeights;

  constructor(
    registry: ModelRegistry = new SimpleModelRegistry(),
    weights: ScoringWeights = SCORING_PRESETS.balanced
  ) {
    this.registry = registry;
    this.weights = weights;
  }

  /**
   * Find the best model for a task.
   */
  findBestModel(task: TaskContext): ModelScore | null {
    const scores = this.scoreAllModels(task);
    if (scores.length === 0) return null;
    return scores[0];
  }

  /**
   * Find top N models for a task.
   */
  findTopModels(task: TaskContext, n: number): ModelScore[] {
    return this.scoreAllModels(task).slice(0, n);
  }

  /**
   * Score all models for a task.
   */
  scoreAllModels(task: TaskContext): ModelScore[] {
    const models = this.registry.listModels();
    const scores: ModelScore[] = [];

    for (const model of models) {
      const score = this.scoreModel(model, task);
      if (score.capabilityScore > 0) {
        // Only include capable models
        scores.push(score);
      }
    }

    // Sort by total score descending
    return scores.sort((a, b) => b.totalScore - a.totalScore);
  }

  /**
   * Score a single model for a task.
   */
  scoreModel(model: ModelCapability, task: TaskContext): ModelScore {
    const reasons: string[] = [];

    // Capability score: does the model meet requirements?
    const capabilityScore = this.calculateCapabilityScore(model, task, reasons);

    // Cost score: how cheap is this model?
    const costScore = this.calculateCostScore(model, task, reasons);

    // Latency score: how fast is this model?
    const latencyScore = this.calculateLatencyScore(model, task, reasons);

    // Quality score: how good is this model's output?
    const qualityScore = this.calculateQualityScore(model, task, reasons);

    // Reliability score: how reliable is this model?
    const reliabilityScore = model.reliabilityScore / 100;

    // Weighted total
    const totalScore =
      capabilityScore * this.weights.capability +
      costScore * this.weights.cost +
      latencyScore * this.weights.latency +
      qualityScore * this.weights.quality +
      reliabilityScore * this.weights.reliability;

    return {
      model: model.model,
      totalScore,
      capabilityScore,
      costScore,
      latencyScore,
      qualityScore,
      reliabilityScore,
      reasons,
    };
  }

  /**
   * Calculate capability score.
   */
  private calculateCapabilityScore(
    model: ModelCapability,
    task: TaskContext,
    reasons: string[]
  ): number {
    let score = 1.0;
    let disqualified = false;

    // Check hard requirements
    if (task.requiresTools && !model.supportsTools) {
      reasons.push('Does not support tools (required)');
      disqualified = true;
    }

    if (task.requiresVision && !model.supportsVision) {
      reasons.push('Does not support vision (required)');
      disqualified = true;
    }

    if (task.requiresStructuredOutput && !model.supportsStructuredOutput) {
      reasons.push('Does not support structured output (required)');
      disqualified = true;
    }

    if (task.estimatedInputTokens > model.maxTokens) {
      reasons.push(`Context too large (${task.estimatedInputTokens} > ${model.maxTokens})`);
      disqualified = true;
    }

    if (disqualified) return 0;

    // Soft scoring for features
    if (task.requiresTools && model.supportsTools) {
      reasons.push('Supports tools');
    }
    if (task.requiresVision && model.supportsVision) {
      reasons.push('Supports vision');
    }

    // Context headroom bonus
    const contextUtilization = task.estimatedInputTokens / model.maxTokens;
    if (contextUtilization < 0.5) {
      score += 0.1;
      reasons.push('Good context headroom');
    }

    return Math.min(1, score);
  }

  /**
   * Calculate cost score (inverse - lower cost = higher score).
   */
  private calculateCostScore(
    model: ModelCapability,
    task: TaskContext,
    reasons: string[]
  ): number {
    // Estimate total cost
    const inputCost = (task.estimatedInputTokens / 1000) * model.costPer1kInput;
    const outputTokens = this.estimateOutputTokens(task);
    const outputCost = (outputTokens / 1000) * model.costPer1kOutput;
    const totalCost = inputCost + outputCost;

    // Check budget constraint
    if (task.maxCost !== undefined && totalCost > task.maxCost) {
      reasons.push(`Exceeds budget ($${totalCost.toFixed(4)} > $${task.maxCost})`);
      return 0;
    }

    // Normalize cost score (using $1 as reference point)
    const costScore = Math.max(0, 1 - totalCost);

    if (totalCost < 0.01) {
      reasons.push(`Very cheap ($${totalCost.toFixed(4)})`);
    } else if (totalCost < 0.1) {
      reasons.push(`Affordable ($${totalCost.toFixed(4)})`);
    } else {
      reasons.push(`Expensive ($${totalCost.toFixed(4)})`);
    }

    return costScore;
  }

  /**
   * Calculate latency score (inverse - lower latency = higher score).
   */
  private calculateLatencyScore(
    model: ModelCapability,
    task: TaskContext,
    reasons: string[]
  ): number {
    const thresholds: Record<string, number> = {
      fast: 500,
      normal: 2000,
      relaxed: 10000,
    };

    const threshold = thresholds[task.latencyRequirement];

    if (model.latencyMs <= threshold) {
      reasons.push(`Meets latency requirement (${model.latencyMs}ms ≤ ${threshold}ms)`);
      // Bonus for being faster than required
      return 1 - model.latencyMs / (threshold * 2);
    } else {
      reasons.push(`May be slow (${model.latencyMs}ms > ${threshold}ms target)`);
      // Penalty for being slower
      return Math.max(0, 1 - model.latencyMs / 10000);
    }
  }

  /**
   * Calculate quality score based on task requirements.
   */
  private calculateQualityScore(
    model: ModelCapability,
    task: TaskContext,
    reasons: string[]
  ): number {
    const requirements: Record<string, number> = {
      maximum: 90,
      high: 80,
      medium: 60,
      low: 0,
    };

    const required = requirements[task.qualityRequirement];

    if (model.qualityScore >= required) {
      reasons.push(`Quality meets requirement (${model.qualityScore} ≥ ${required})`);
      return model.qualityScore / 100;
    } else {
      reasons.push(`Quality below requirement (${model.qualityScore} < ${required})`);
      return model.qualityScore / 100 * 0.5; // Penalty
    }
  }

  /**
   * Estimate output tokens based on task.
   */
  private estimateOutputTokens(task: TaskContext): number {
    const sizeMultipliers: Record<string, number> = {
      small: 100,
      medium: 500,
      large: 2000,
    };
    return sizeMultipliers[task.expectedOutputSize];
  }

  /**
   * Convert scores to alternatives format.
   */
  scoresToAlternatives(scores: ModelScore[]): ModelAlternative[] {
    return scores.map((s) => ({
      model: s.model,
      score: s.totalScore,
      reason: s.reasons.slice(0, 2).join('; '),
    }));
  }

  /**
   * Update scoring weights.
   */
  setWeights(weights: ScoringWeights): void {
    this.weights = weights;
  }

  /**
   * Use a preset.
   */
  usePreset(preset: keyof typeof SCORING_PRESETS): void {
    this.weights = SCORING_PRESETS[preset];
  }
}

// =============================================================================
// TASK ANALYZER
// =============================================================================

/**
 * Analyze task text to infer context.
 */
export function analyzeTaskText(taskText: string): Partial<TaskContext> {
  const text = taskText.toLowerCase();
  const inferred: Partial<TaskContext> = {};

  // Infer task type
  if (text.includes('code') || text.includes('implement') || text.includes('function')) {
    inferred.taskType = 'code_generation';
  } else if (text.includes('review') || text.includes('check')) {
    inferred.taskType = 'code_review';
  } else if (text.includes('summarize') || text.includes('summary')) {
    inferred.taskType = 'summarization';
  } else if (text.includes('translate')) {
    inferred.taskType = 'translation';
  } else if (text.includes('analyze') || text.includes('analysis')) {
    inferred.taskType = 'analysis';
  } else if (text.includes('write') || text.includes('creative')) {
    inferred.taskType = 'creative_writing';
  } else if (text.includes('extract') || text.includes('parse')) {
    inferred.taskType = 'extraction';
  } else if (text.includes('classify') || text.includes('categorize')) {
    inferred.taskType = 'classification';
  } else if (text.includes('reason') || text.includes('think') || text.includes('explain why')) {
    inferred.taskType = 'reasoning';
  }

  // Infer requirements
  if (text.includes('image') || text.includes('picture') || text.includes('screenshot')) {
    inferred.requiresVision = true;
  }

  if (text.includes('json') || text.includes('structured')) {
    inferred.requiresStructuredOutput = true;
  }

  if (text.includes('search') || text.includes('tool') || text.includes('browse')) {
    inferred.requiresTools = true;
  }

  // Infer quality
  if (text.includes('best') || text.includes('highest quality') || text.includes('perfect')) {
    inferred.qualityRequirement = 'maximum';
  } else if (text.includes('quick') || text.includes('simple') || text.includes('draft')) {
    inferred.qualityRequirement = 'low';
  }

  // Infer latency
  if (text.includes('fast') || text.includes('quick') || text.includes('asap')) {
    inferred.latencyRequirement = 'fast';
  }

  return inferred;
}

// =============================================================================
// EXPORTS
// =============================================================================

export function createCapabilityMatcher(
  registry?: ModelRegistry,
  weights?: ScoringWeights
): CapabilityMatcher {
  return new CapabilityMatcher(registry, weights);
}

export function createModelRegistry(
  capabilities?: ModelCapability[]
): SimpleModelRegistry {
  return new SimpleModelRegistry(capabilities);
}
