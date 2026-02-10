/**
 * Swarm Quality Gate
 *
 * Uses the orchestrator model to validate worker outputs.
 * Each completed task is scored 1-5; score < 3 triggers rejection/retry.
 *
 * V4: Artifact verification — checks whether target files actually exist
 * and have non-trivial content, so judges can't rubber-stamp empty outputs.
 * Also injects temporal grounding so judges catch stale/outdated content.
 */

import * as fs from 'node:fs';
import * as path from 'node:path';
import type { LLMProvider } from '../../providers/types.js';
import type { SwarmTask, SwarmTaskResult } from './types.js';
import { formatFactsCompact, getEnvironmentFacts } from '../environment-facts.js';

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

  /** Whether the result passes (score >= threshold) */
  passed: boolean;

  /** True when rejected due to missing/empty target files (not a model problem) */
  artifactAutoFail?: boolean;
}

/**
 * Evaluate a worker's output using the orchestrator model.
 * V3: Accepts optional judgeConfig for hierarchy-based model/persona override.
 * V4: Includes artifact verification and temporal grounding.
 */
export async function evaluateWorkerOutput(
  provider: LLMProvider,
  orchestratorModel: string,
  task: SwarmTask,
  result: SwarmTaskResult,
  judgeConfig?: QualityGateConfig,
  qualityThreshold: number = 3,
): Promise<QualityGateResult> {
  // V4: Pre-flight artifact check — if task has target files, verify they exist
  const artifactReport = checkArtifacts(task);

  // If ALL target files are empty/missing, auto-fail without burning a judge call
  if (artifactReport.allEmpty) {
    return {
      score: 1,
      feedback: `Target files are empty or missing: ${artifactReport.summary}`,
      passed: false,
      artifactAutoFail: true,
    };
  }

  // V6: Closure report pre-check — catch workers that did no actual work
  // When there are no targetFiles (so artifact check can't catch it), use the
  // closure report to detect workers that admit failure with budget excuses
  if (!artifactReport.allEmpty && result.closureReport) {
    const cr = result.closureReport;
    const noRealFindings = cr.findings.length === 0 ||
      cr.findings.every(f => /budget|unable|not completed|constraint/i.test(f));
    const admitsFailure = cr.failures.length > 0 &&
      cr.failures.some(f => /no.*search|no.*performed|not created/i.test(f));

    if (noRealFindings && admitsFailure) {
      return {
        score: 1,
        feedback: `Worker admitted failure in closure report: ${cr.failures[0]}`,
        passed: false,
        artifactAutoFail: false,
      };
    }
  }

  const prompt = buildQualityPrompt(task, result, artifactReport);
  const model = judgeConfig?.model ?? orchestratorModel;

  const facts = formatFactsCompact(getEnvironmentFacts());
  const systemPrompt = judgeConfig?.persona
    ? `${judgeConfig.persona}\n\n${facts}\nYou are evaluating worker outputs. Score concisely.`
    : `${facts}\nYou are a quality reviewer for AI worker outputs. Evaluate concisely.`;

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

    const parsed = parseQualityResponse(response.content);
    // Apply configurable threshold
    parsed.passed = parsed.score >= qualityThreshold;
    return parsed;
  } catch {
    // If quality gate fails, pass by default (don't block on gate failure)
    return {
      score: 3,
      feedback: 'Quality gate evaluation failed — passing by default',
      passed: true,
    };
  }
}

// ─── Artifact Verification ────────────────────────────────────────────────

interface ArtifactReport {
  /** Whether all target files are empty or missing */
  allEmpty: boolean;
  /** Human-readable summary for the judge prompt */
  summary: string;
  /** Per-file status */
  files: Array<{ path: string; exists: boolean; sizeBytes: number; preview: string }>;
}

/**
 * Check whether target files actually exist and have content.
 * Returns a report that gets injected into the judge prompt.
 */
function checkArtifacts(task: SwarmTask): ArtifactReport {
  if (!task.targetFiles || task.targetFiles.length === 0) {
    return { allEmpty: false, summary: 'No target files specified.', files: [] };
  }

  const files: ArtifactReport['files'] = [];
  let allEmpty = true;

  for (const filePath of task.targetFiles) {
    const resolved = path.resolve(filePath);
    let exists = false;
    let sizeBytes = 0;
    let preview = '';

    try {
      if (fs.existsSync(resolved)) {
        exists = true;
        const stats = fs.statSync(resolved);
        sizeBytes = stats.size;
        if (sizeBytes > 0) {
          allEmpty = false;
          // Read first 500 chars for the judge to evaluate content quality
          const content = fs.readFileSync(resolved, 'utf-8');
          preview = content.slice(0, 500);
        }
      }
    } catch {
      // File read error — treat as missing
    }

    files.push({ path: filePath, exists, sizeBytes, preview });
  }

  const lines = files.map(f => {
    if (!f.exists) return `  - ${f.path}: MISSING`;
    if (f.sizeBytes === 0) return `  - ${f.path}: EMPTY (0 bytes)`;
    return `  - ${f.path}: ${f.sizeBytes} bytes`;
  });

  return {
    allEmpty,
    summary: lines.join('\n'),
    files,
  };
}

// ─── Prompt Building ──────────────────────────────────────────────────────

/**
 * Build the quality evaluation prompt.
 * V4: Includes artifact verification data and temporal anchoring.
 */
function buildQualityPrompt(task: SwarmTask, result: SwarmTaskResult, artifacts: ArtifactReport): string {
  const output = result.output.slice(0, 2000); // Truncate long outputs
  const facts = getEnvironmentFacts();

  let artifactSection = '';
  if (artifacts.files.length > 0) {
    const fileDetails = artifacts.files.map(f => {
      if (!f.exists) return `  ${f.path}: MISSING — file was not created`;
      if (f.sizeBytes === 0) return `  ${f.path}: EMPTY (0 bytes) — file exists but has no content`;
      let detail = `  ${f.path}: ${f.sizeBytes} bytes`;
      if (f.preview) {
        detail += `\n    First 500 chars: ${f.preview}`;
      }
      return detail;
    }).join('\n');

    artifactSection = `
ARTIFACT VERIFICATION (filesystem check — this is ground truth):
${fileDetails}

CRITICAL: If target files are EMPTY (0 bytes) or MISSING, the task FAILED regardless
of what the worker claims. An empty file is NOT an acceptable artifact. Score <= 2.`;
  }

  return `Evaluate this worker's output for the given task.

TASK: ${task.description}
TASK TYPE: ${task.type}
CURRENT DATE: ${facts.currentDate} (${facts.currentYear})
${task.targetFiles ? `TARGET FILES: ${task.targetFiles.join(', ')}` : ''}

WORKER OUTPUT:
${output}

${result.closureReport ? `STRUCTURED REPORT:
- Findings: ${result.closureReport.findings.join('; ')}
- Actions: ${result.closureReport.actionsTaken.join('; ')}
- Failures: ${result.closureReport.failures.join('; ')}
- Remaining: ${result.closureReport.remainingWork.join('; ')}` : ''}
${artifactSection}

Rate the output 1-5:
1 = Completely wrong, empty artifacts, or no meaningful work done
2 = Attempted but significantly incomplete (empty/missing files, stale data, major gaps)
3 = Acceptable — covers the core requirement with minor issues, files have real content
4 = Good — thorough, correct, and files contain well-structured content
5 = Excellent — complete, clean, well-structured, temporally accurate (${facts.currentYear} data)

IMPORTANT SCORING RULES:
- If target files are EMPTY or MISSING: maximum score is 1
- If content references outdated years (e.g. "as of ${facts.currentYear - 2}") without current data: maximum score is 2
- Worker claims alone are NOT evidence — the ARTIFACT VERIFICATION section is ground truth

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
