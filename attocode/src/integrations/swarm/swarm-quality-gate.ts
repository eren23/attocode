/**
 * Swarm Quality Gate
 *
 * Uses the orchestrator model to validate worker outputs.
 * Each completed task is scored 1-5; score < 3 triggers rejection/retry.
 */

import type { LLMProvider } from '../../providers/types.js';
import type { SwarmTask, SwarmTaskResult } from './types.js';

// ─── Quality Gate Config ──────────────────────────────────────────────────

/** Optional judge role configuration for quality gates. */
export interface QualityGateConfig {
  /** Judge model override (uses orchestratorModel if not set) */
  model?: string;
  /** Judge persona for system prompt */
  persona?: string;
}

// ─── Quality Gate ──────────────────────────────────────────────────────────

export interface QualityGateResult {
  /** Score 1-5 */
  score: number;

  /** Feedback explaining the score */
  feedback: string;

  /** Whether the result passes (score >= 3) */
  passed: boolean;
}

/**
 * Evaluate a worker's output using the orchestrator model.
 * V3: Accepts optional judgeConfig for hierarchy-based model/persona override.
 */
export async function evaluateWorkerOutput(
  provider: LLMProvider,
  orchestratorModel: string,
  task: SwarmTask,
  result: SwarmTaskResult,
  judgeConfig?: QualityGateConfig,
): Promise<QualityGateResult> {
  const prompt = buildQualityPrompt(task, result);
  const model = judgeConfig?.model ?? orchestratorModel;
  const systemPrompt = judgeConfig?.persona
    ? `${judgeConfig.persona}\n\nYou are evaluating worker outputs. Score concisely.`
    : 'You are a quality reviewer for AI worker outputs. Evaluate concisely.';

  try {
    const response = await provider.chat(
      [
        { role: 'system', content: systemPrompt },
        { role: 'user', content: prompt },
      ],
      {
        model,
        maxTokens: 500,
        temperature: 0.1,
      },
    );

    return parseQualityResponse(response.content);
  } catch {
    // If quality gate fails, pass by default (don't block on gate failure)
    return {
      score: 3,
      feedback: 'Quality gate evaluation failed — passing by default',
      passed: true,
    };
  }
}

/**
 * Build the quality evaluation prompt.
 */
function buildQualityPrompt(task: SwarmTask, result: SwarmTaskResult): string {
  const output = result.output.slice(0, 2000); // Truncate long outputs

  return `Evaluate this worker's output for the given task.

TASK: ${task.description}
TASK TYPE: ${task.type}
${task.targetFiles ? `TARGET FILES: ${task.targetFiles.join(', ')}` : ''}

WORKER OUTPUT:
${output}

${result.closureReport ? `STRUCTURED REPORT:
- Findings: ${result.closureReport.findings.join('; ')}
- Actions: ${result.closureReport.actionsTaken.join('; ')}
- Failures: ${result.closureReport.failures.join('; ')}
- Remaining: ${result.closureReport.remainingWork.join('; ')}` : ''}

Rate the output 1-5:
1 = Completely wrong or empty
2 = Attempted but significantly incomplete/incorrect
3 = Acceptable — covers the core requirement with minor issues
4 = Good — thorough and correct
5 = Excellent — complete, clean, well-structured

Respond in EXACTLY this format:
SCORE: <number>
FEEDBACK: <one-line explanation>`;
}

/**
 * Parse the quality gate response.
 */
function parseQualityResponse(content: string): QualityGateResult {
  // Extract score (M4: match multi-digit numbers like "10")
  const scoreMatch = content.match(/SCORE:\s*(\d+)/i);
  const score = scoreMatch ? parseInt(scoreMatch[1], 10) : 3;
  const clampedScore = Math.max(1, Math.min(5, score));

  // Extract feedback
  const feedbackMatch = content.match(/FEEDBACK:\s*(.+)/i);
  const feedback = feedbackMatch ? feedbackMatch[1].trim() : content.slice(0, 200);

  return {
    score: clampedScore,
    feedback,
    passed: clampedScore >= 3,
  };
}
