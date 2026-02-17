/**
 * Swarm Helpers — Standalone helper functions and constants extracted from swarm-orchestrator.ts.
 *
 * These were moved here to break the circular dependency:
 *   swarm-orchestrator.ts <-> swarm-execution.ts / swarm-recovery.ts
 *
 * swarm-execution.ts and swarm-recovery.ts now import these from swarm-helpers.ts
 * instead of swarm-orchestrator.ts. swarm-orchestrator.ts re-exports them for
 * backward compatibility.
 */

import * as fs from 'node:fs';
import * as path from 'node:path';
import type { SwarmConfig } from './types.js';
import { getTaskTypeConfig } from './types.js';
import type { SpawnResult } from '../agents/agent-registry.js';
import type { SwarmEvent } from './swarm-events.js';

// ─── Hollow Completion Detection ──────────────────────────────────────────

/**
 * V11: Hollow completion detection — catches empty completions AND "success" with failure language.
 * Zero tool calls AND trivial output is always hollow.
 * Additionally, success=true but output containing failure admissions is also hollow —
 * this catches workers that report success but actually did no useful work.
 */
export const FAILURE_INDICATORS = [
  'budget exhausted',
  'unable to complete',
  'could not complete',
  'ran out of budget',
  'no changes were made',
  'no files were modified',
  'no files were created',
  'failed to complete',
  'before research could begin',
  'i was unable to',
  'i could not',
  'unfortunately i',
];

export const BOILERPLATE_INDICATORS = [
  'task completed successfully',
  'i have completed the task',
  'the task has been completed',
  'done',
  'completed',
  'finished',
  'no issues found',
  'everything looks good',
  'all tasks completed',
];

export function hasFutureIntentLanguage(content: string): boolean {
  const trimmed = content.trim();
  if (!trimmed) return false;
  const lower = trimmed.toLowerCase();
  const completionSignals =
    /\b(done|completed|finished|created|saved|wrote|implemented|fixed|updated|added)\b/;
  if (completionSignals.test(lower)) return false;
  const futureIntentPatterns: RegExp[] = [
    /\b(i\s+will|i'll|let me)\s+(create|write|save|update|modify|fix|add|edit|implement|change|run|execute|build|continue)\b/,
    /\b(i\s+need to|i\s+should|i\s+can)\s+(create|write|update|modify|fix|add|edit|implement|continue)\b/,
    /\b(next step|remaining work|still need|to be done)\b/,
    /\b(i am going to|i'm going to)\b/,
  ];
  return futureIntentPatterns.some((p) => p.test(lower));
}

export function repoLooksUnscaffolded(baseDir: string): boolean {
  try {
    const packageJson = path.join(baseDir, 'package.json');
    const srcDir = path.join(baseDir, 'src');
    if (!fs.existsSync(packageJson) && !fs.existsSync(srcDir)) {
      return true;
    }
  } catch {
    return false;
  }
  return false;
}

export function isHollowCompletion(
  spawnResult: SpawnResult,
  taskType?: string,
  swarmConfig?: SwarmConfig,
): boolean {
  // Timeout uses toolCalls === -1, not hollow
  if ((spawnResult.metrics.toolCalls ?? 0) === -1) return false;

  const toolCalls = spawnResult.metrics.toolCalls ?? 0;

  // Truly empty completions: zero tools AND trivial output
  const hollowThreshold = swarmConfig?.hollowOutputThreshold ?? 120;
  if (toolCalls === 0 && (spawnResult.output?.trim().length ?? 0) < hollowThreshold) {
    return true;
  }

  // P4: Boilerplate detection
  if (toolCalls === 0 && (spawnResult.output?.trim().length ?? 0) < 300) {
    const outputLower = (spawnResult.output ?? '').toLowerCase().trim();
    if (BOILERPLATE_INDICATORS.some((b) => outputLower.includes(b))) {
      return true;
    }
  }

  // "Success" that admits failure
  if (spawnResult.success) {
    const outputLower = (spawnResult.output ?? '').toLowerCase();
    if (FAILURE_INDICATORS.some((f) => outputLower.includes(f))) {
      return true;
    }
  }

  // V7: Use configurable requiresToolCalls from TaskTypeConfig
  if (taskType) {
    const typeConfig = getTaskTypeConfig(taskType, swarmConfig);
    if (typeConfig.requiresToolCalls && toolCalls === 0) {
      return true;
    }
  }

  return false;
}

// ─── Event Emitter ─────────────────────────────────────────────────────────

export type SwarmEventListener = (event: SwarmEvent) => void;
