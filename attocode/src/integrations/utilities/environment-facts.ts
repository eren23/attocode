/**
 * Environment Facts
 *
 * Core grounding module that provides temporal, platform, and project
 * context to all agents (main, subagent, swarm worker, quality gate).
 *
 * Without this, LLMs confidently write "as of 2024" when it's 2026,
 * cite stale data as current, and produce artifacts that fail temporal
 * verification.
 *
 * Usage:
 *   const facts = getEnvironmentFacts();           // auto-populated singleton
 *   const block = formatFactsBlock(facts);          // for system prompts
 *   const line  = formatFactsCompact(facts);        // for judge prompts
 */

import { platform, arch } from 'node:os';

// ─── Types ────────────────────────────────────────────────────────────────

export interface EnvironmentFacts {
  /** Current date in YYYY-MM-DD format */
  currentDate: string;

  /** Current year */
  currentYear: number;

  /** Current month name (e.g. "February") */
  currentMonth: string;

  /** Working directory */
  workingDirectory: string;

  /** Platform (darwin, linux, win32) */
  platform: string;

  /** Architecture (arm64, x64) */
  arch: string;

  /** Node.js version */
  nodeVersion: string;

  /** User-provided custom facts (from swarm.yaml or config) */
  custom: string[];
}

// ─── Singleton ────────────────────────────────────────────────────────────

let _cached: EnvironmentFacts | null = null;

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

/**
 * Get auto-populated environment facts.
 * Cached per process — call refreshEnvironmentFacts() to force update.
 */
export function getEnvironmentFacts(customFacts?: string[]): EnvironmentFacts {
  if (_cached && !customFacts) return _cached;

  const now = new Date();
  const facts: EnvironmentFacts = {
    currentDate: now.toISOString().split('T')[0],
    currentYear: now.getFullYear(),
    currentMonth: MONTHS[now.getMonth()],
    workingDirectory: process.cwd(),
    platform: platform(),
    arch: arch(),
    nodeVersion: process.version,
    custom: customFacts ?? _cached?.custom ?? [],
  };

  _cached = facts;
  return facts;
}

/**
 * Force refresh (e.g. if cwd changes or date rolls over).
 */
export function refreshEnvironmentFacts(customFacts?: string[]): EnvironmentFacts {
  _cached = null;
  return getEnvironmentFacts(customFacts);
}

// ─── Formatters ───────────────────────────────────────────────────────────

/**
 * Format facts as a full system prompt block.
 * Used by main agent and swarm worker system prompts.
 */
export function formatFactsBlock(facts?: EnvironmentFacts): string {
  const f = facts ?? getEnvironmentFacts();
  const lines = [
    '═══ ENVIRONMENT FACTS ═══',
    '',
    `Today's date: ${f.currentDate} (${f.currentMonth} ${f.currentYear})`,
    `Working directory: ${f.workingDirectory}`,
    `Platform: ${f.platform}/${f.arch}, Node ${f.nodeVersion}`,
    '',
    'IMPORTANT: When researching, writing reports, or referencing current events,',
    `use ${f.currentYear} as the current year. Your training data may be outdated —`,
    'prefer web search results over internal knowledge for recent facts.',
  ];

  if (f.custom.length > 0) {
    lines.push('', 'Additional context:');
    for (const fact of f.custom) {
      lines.push(`- ${fact}`);
    }
  }

  return lines.join('\n');
}

/**
 * Format facts as a compact one-liner for judge/gate prompts.
 */
export function formatFactsCompact(facts?: EnvironmentFacts): string {
  const f = facts ?? getEnvironmentFacts();
  return `Current date: ${f.currentDate}. Current year: ${f.currentYear}. Working directory: ${f.workingDirectory}.`;
}
