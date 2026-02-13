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
import type { SwarmTask, SwarmTaskResult, SwarmConfig } from './types.js';
import { getTaskTypeConfig } from './types.js';
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

  /** True when rejection is a pre-flight auto-reject (no LLM judge call made).
   *  Pre-flight rejects should NOT count toward the circuit breaker counter. */
  preFlightReject?: boolean;

  /** P5: True when the quality gate evaluation itself failed (LLM error) */
  gateError?: boolean;

  /** P5: Error message when gate evaluation failed */
  gateErrorMessage?: string;
}

/**
 * Run cheap, synchronous pre-flight checks on a task result.
 * Returns a failing QualityGateResult on the first check that trips, or null if all pass.
 *
 * Checks: V4 artifact verification, V9 zero-tool-call, V10 file-creation intent, V6 closure report.
 */
export function runPreFlightChecks(task: SwarmTask, result: SwarmTaskResult, swarmConfig?: SwarmConfig, cachedArtifacts?: { allEmpty: boolean; summary: string; files: Array<{ path: string; exists: boolean; sizeBytes: number; preview: string }> }): QualityGateResult | null {
  // V4: Pre-flight artifact check — if task has target files, verify they exist
  // C1: Accept pre-computed artifacts to avoid double filesystem scan
  const artifactReport = cachedArtifacts ?? checkArtifacts(task);

  // If ALL target files are empty/missing, auto-fail without burning a judge call
  if (artifactReport.allEmpty) {
    return {
      score: 1,
      feedback: `Target files are empty or missing: ${artifactReport.summary}`,
      passed: false,
      artifactAutoFail: true,
      preFlightReject: true,
    };
  }

  // V7: Tool-call pre-check using configurable requiresToolCalls from TaskTypeConfig.
  const typeConfig = getTaskTypeConfig(task.type, swarmConfig);
  if (typeConfig.requiresToolCalls && (result.toolCalls ?? 0) === 0) {
    return {
      score: 0,
      feedback: 'No tool calls made — no work was done.',
      passed: false,
      preFlightReject: true,
    };
  }

  // V10: File-creation intent pre-check — if the task description strongly implies
  // file creation (e.g., "Write to report/X.md") but the worker produced no files,
  // auto-reject. This catches workers that lacked write tools but still produced
  // rich text output (which would pass the hollow-completion check).
  if ((result.filesModified ?? []).length === 0 && (result.toolCalls ?? 0) === 0) {
    const hasWriteIntent = /\b(write|create|generate|produce|save)\b.*\b(file|report|document|output)\b/i.test(task.description)
      || /\b(write_file|write to|save to|output to)\b/i.test(task.description)
      || (task.targetFiles && task.targetFiles.length > 0);
    if (hasWriteIntent) {
      return {
        score: 1,
        feedback: `Task requires file creation but worker produced 0 files and made 0 tool calls — likely missing write_file tool.`,
        passed: false,
        artifactAutoFail: true,
        preFlightReject: true,
      };
    }
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
        preFlightReject: true,
      };
    }
  }

  return null;
}

// ─── F2: Concrete Output Validation ─────────────────────────────────────────

export interface ConcreteCheckResult {
  passed: boolean;
  issues: string[];
}

/**
 * F2: Run concrete validation checks on task output.
 *
 * Validates that modified files are syntactically valid (parseable) and that
 * claimed file modifications match actual filesystem state. This provides
 * ground-truth validation that catches broken outputs before the LLM judge.
 *
 * Checks:
 * 1. For implement/test/refactor tasks: verify modified .ts/.js/.json files parse
 * 2. For test tasks: verify test file is syntactically valid
 * 3. Verify filesModified in closure report matches actual filesystem changes
 */
export function runConcreteChecks(task: SwarmTask, result: SwarmTaskResult): ConcreteCheckResult {
  const issues: string[] = [];

  const filesModified = result.filesModified ?? [];
  const actionTypes = ['implement', 'test', 'refactor', 'fix', 'create', 'merge'];
  const isCodeTask = actionTypes.includes(task.type);

  // Check 1: Verify modified files exist and are syntactically valid
  if (isCodeTask && filesModified.length > 0) {
    for (const filePath of filesModified) {
      const resolved = path.resolve(filePath);
      try {
        if (!fs.existsSync(resolved)) {
          issues.push(`Modified file missing: ${filePath}`);
          continue;
        }
        const stat = fs.statSync(resolved);
        if (stat.size === 0) {
          issues.push(`Modified file is empty: ${filePath}`);
          continue;
        }

        // Syntax check for parseable file types
        const ext = path.extname(filePath).toLowerCase();
        if (ext === '.json') {
          const content = fs.readFileSync(resolved, 'utf-8');
          try {
            JSON.parse(content);
          } catch {
            issues.push(`Invalid JSON syntax: ${filePath}`);
          }
        }
        // For .ts/.js files, check for obvious syntax issues
        // (incomplete files, unmatched braces, etc.)
        if (['.ts', '.tsx', '.js', '.jsx', '.mts', '.mjs'].includes(ext)) {
          const content = fs.readFileSync(resolved, 'utf-8');
          // Check for grossly unbalanced braces (indicates truncated/corrupt file)
          const opens = (content.match(/\{/g) || []).length;
          const closes = (content.match(/\}/g) || []).length;
          if (Math.abs(opens - closes) > 3) {
            issues.push(`Unbalanced braces (${opens} open, ${closes} close): ${filePath}`);
          }
        }
      } catch {
        // Can't read file — not necessarily an issue
      }
    }
  }

  // Check 2: Verify closure report filesModified matches actual changes
  if (result.closureReport && result.closureReport.actionsTaken.length > 0) {
    const claimedFiles = filesModified;
    const missingClaimed = claimedFiles.filter(f => {
      try {
        return !fs.existsSync(path.resolve(f));
      } catch {
        return true;
      }
    });
    if (missingClaimed.length > 0 && missingClaimed.length === claimedFiles.length) {
      issues.push(`All claimed modified files are missing: ${missingClaimed.join(', ')}`);
    }
  }

  return {
    passed: issues.length === 0,
    issues,
  };
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
  onUsage?: (response: { usage?: { total_tokens?: number; prompt_tokens?: number; completion_tokens?: number } }, purpose: string) => void,
  fileArtifacts?: Array<{ path: string; preview: string }>,
  swarmConfig?: SwarmConfig,
  cachedArtifactReport?: ArtifactReport,
): Promise<QualityGateResult> {
  // C1: Use cached artifact report if provided, otherwise compute once
  const artifactReport = cachedArtifactReport ?? checkArtifacts(task);

  // Run synchronous pre-flight checks first
  const preFlight = runPreFlightChecks(task, result, swarmConfig, artifactReport);
  if (preFlight) {
    return preFlight;
  }

  const prompt = buildQualityPrompt(task, result, artifactReport, fileArtifacts);
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
        maxTokens: 800,
        temperature: 0.1,
      },
    );

    // Track quality gate LLM usage for orchestrator stats
    onUsage?.(response as any, 'quality-gate');

    const parsed = parseQualityResponse(response.content);
    // Apply configurable threshold
    parsed.passed = parsed.score >= qualityThreshold;
    return parsed;
  } catch (error) {
    // F7: Quality gate error → fail by default (was: pass by default).
    // The orchestrator checks gateError and falls back to concrete validation.
    return {
      score: 3,
      feedback: `Quality gate evaluation failed (${(error as Error).message?.slice(0, 100) ?? 'unknown error'})`,
      passed: false,
      gateError: true,
      gateErrorMessage: (error as Error).message?.slice(0, 200) ?? 'unknown error',
    };
  }
}

// ─── Artifact Verification ────────────────────────────────────────────────

export interface ArtifactReport {
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
 * Exported so callers can pre-compute and cache the result.
 */
export function checkArtifacts(task: SwarmTask): ArtifactReport {
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
          // Read first 2000 chars for the judge to evaluate content quality
          const content = fs.readFileSync(resolved, 'utf-8');
          preview = content.slice(0, 2000);
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

/**
 * Enhanced artifact detection — searches beyond targetFiles.
 * Used by resilience recovery and rescue pass to find work products
 * that the standard checkArtifacts() would miss (e.g., when targetFiles is empty).
 *
 * Search order:
 * 1. Standard checkArtifacts() for declared targetFiles
 * 2. taskResult.filesModified — scan those paths on disk
 * 3. taskResult.closureReport.actionsTaken — extract file path mentions
 * 4. taskResult.output — regex for file paths
 * 5. De-duplicate, return unified report
 */
export function checkArtifactsEnhanced(
  task: SwarmTask,
  taskResult?: SwarmTaskResult,
  baseDir?: string,
): ArtifactReport {
  const cwd = baseDir ?? process.cwd();
  const seenPaths = new Set<string>();
  const allFiles: ArtifactReport['files'] = [];

  // 1. Standard check for declared targetFiles
  const standard = checkArtifacts(task);
  for (const f of standard.files) {
    if (!seenPaths.has(f.path)) {
      seenPaths.add(f.path);
      allFiles.push(f);
    }
  }

  // Helper to probe a file path on disk and add to report
  const probeFile = (filePath: string) => {
    if (seenPaths.has(filePath)) return;
    seenPaths.add(filePath);
    const resolved = path.isAbsolute(filePath) ? filePath : path.resolve(cwd, filePath);
    try {
      if (fs.existsSync(resolved)) {
        const stats = fs.statSync(resolved);
        if (stats.size > 0) {
          const content = fs.readFileSync(resolved, 'utf-8');
          allFiles.push({
            path: filePath,
            exists: true,
            sizeBytes: stats.size,
            preview: content.slice(0, 2000),
          });
          return;
        }
        allFiles.push({ path: filePath, exists: true, sizeBytes: 0, preview: '' });
        return;
      }
    } catch {
      // File access error — treat as missing
    }
    allFiles.push({ path: filePath, exists: false, sizeBytes: 0, preview: '' });
  };

  if (taskResult) {
    // 2. filesModified from the task result
    if (taskResult.filesModified) {
      for (const fp of taskResult.filesModified) {
        probeFile(fp);
      }
    }

    // 3. closureReport.actionsTaken — extract file paths
    if (taskResult.closureReport?.actionsTaken) {
      for (const action of taskResult.closureReport.actionsTaken) {
        const matches = action.match(/(?:^|\s)([\w./-]+\.\w{1,10})\b/g);
        if (matches) {
          for (const m of matches) {
            const fp = m.trim();
            // Basic sanity: must have a path separator or start with a filename-like pattern
            if (fp.includes('/') || fp.includes('.')) {
              probeFile(fp);
            }
          }
        }
      }
    }

    // 4. output — regex for file paths (conservative: require path separator)
    const outputPathRegex = /(?:^|\s)((?:[\w.-]+\/)+[\w.-]+\.\w{1,10})\b/g;
    let match: RegExpExecArray | null;
    const outputSlice = taskResult.output.slice(0, 8000); // Limit scan length
    while ((match = outputPathRegex.exec(outputSlice)) !== null) {
      const fp = match[1];
      if (fp && !seenPaths.has(fp)) {
        probeFile(fp);
      }
    }
  }

  // Build unified report
  const existingFiles = allFiles.filter(f => f.exists && f.sizeBytes > 0);
  const allEmpty = allFiles.length > 0 && existingFiles.length === 0;

  const lines = allFiles.map(f => {
    if (!f.exists) return `  - ${f.path}: MISSING`;
    if (f.sizeBytes === 0) return `  - ${f.path}: EMPTY (0 bytes)`;
    return `  - ${f.path}: ${f.sizeBytes} bytes`;
  });

  return {
    allEmpty: allFiles.length === 0 ? false : allEmpty,
    summary: allFiles.length === 0 ? 'No artifacts found.' : lines.join('\n'),
    files: allFiles,
  };
}

// ─── Prompt Building ──────────────────────────────────────────────────────

/**
 * Build the quality evaluation prompt.
 * V4: Includes artifact verification data and temporal anchoring.
 */
function buildQualityPrompt(task: SwarmTask, result: SwarmTaskResult, artifacts: ArtifactReport, fileArtifacts?: Array<{ path: string; preview: string }>): string {
  const output = result.output.slice(0, 16000); // Truncate long outputs (16K gives judge enough evidence for multi-file tasks)
  const facts = getEnvironmentFacts();

  let artifactSection = '';
  if (artifacts.files.length > 0) {
    const fileDetails = artifacts.files.map(f => {
      if (!f.exists) return `  ${f.path}: MISSING — file was not created`;
      if (f.sizeBytes === 0) return `  ${f.path}: EMPTY (0 bytes) — file exists but has no content`;
      let detail = `  ${f.path}: ${f.sizeBytes} bytes`;
      if (f.preview) {
        detail += `\n    First 2000 chars: ${f.preview}`;
      }
      return detail;
    }).join('\n');

    artifactSection = `
ARTIFACT VERIFICATION (filesystem check — this is ground truth):
${fileDetails}

CRITICAL: If target files are EMPTY (0 bytes) or MISSING, the task FAILED regardless
of what the worker claims. An empty file is NOT an acceptable artifact. Score <= 2.`;
  }

  // Build file artifacts section from worker tool calls (write_file/edit_file results)
  let fileArtifactsSection = '';
  if (fileArtifacts && fileArtifacts.length > 0) {
    const artifactDetails = fileArtifacts
      .slice(0, 10) // Limit to 10 files
      .map(f => `  ${f.path}:\n    ${f.preview.slice(0, 1500)}`)
      .join('\n');
    fileArtifactsSection = `
FILES CREATED/MODIFIED BY WORKER (from tool call results — ground truth):
${artifactDetails}

NOTE: These are actual file contents extracted from write_file/edit_file tool calls.
They prove the worker did real work beyond just text claims.`;
  }

  return `Evaluate this worker's output for the given task.

TASK: ${task.description}
TASK TYPE: ${task.type}
WORKER METRICS: ${result.toolCalls ?? 0} tool calls, ${fileArtifacts?.length ?? 0} files created/modified, ${result.tokensUsed} tokens used
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
${fileArtifactsSection}

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
FEEDBACK: <one-line explanation>
CONCRETE_FIXES: <If score < 3, list 1-3 specific fixes the worker must make. Reference exact file names, functions, or missing pieces. If score >= 3, write "N/A">`;
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
  let feedback = feedbackMatch ? feedbackMatch[1].trim() : content.slice(0, 200);

  // Extract concrete fixes (appended to feedback for retry context)
  const fixesMatch = content.match(/CONCRETE_FIXES:\s*(.+)/i);
  if (fixesMatch) {
    const fixes = fixesMatch[1].trim();
    if (fixes && fixes !== 'N/A') {
      feedback = feedback + ' | Fixes: ' + fixes;
    }
  }

  return {
    score: clampedScore,
    feedback,
    passed: clampedScore >= 3,
  };
}
