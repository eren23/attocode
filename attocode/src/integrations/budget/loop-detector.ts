/**
 * Loop Detector - Doom loop and pattern detection for the economics system.
 *
 * Extracted from economics.ts (Phase 3b restructuring).
 *
 * Handles:
 * - Exact and fuzzy doom loop detection (same tool+args repeated)
 * - Bash file-read normalization (cat/head/tail targeting same file)
 * - Structural fingerprinting for near-identical calls
 * - Test-fix cycle detection
 * - Bash failure cascade detection
 * - Summary loop detection (consecutive text-only turns)
 */

import { stableStringify } from '../context/context-engineering.js';
import type { LoopDetectionState, EconomicsTuning, PhaseState } from './economics.js';

// =============================================================================
// CONSTANTS
// =============================================================================

/**
 * Regex for common bash file-read commands (simple, no pipes/redirects).
 * Captures the file path for normalized doom loop fingerprinting.
 */
const BASH_FILE_READ_RE = /^\s*(cat|head|tail|wc|less|more|file|stat|md5sum|sha256sum)\b(?:\s+-[^\s]+)*\s+((?:\/|\.\/|\.\.\/)[\w.\/\-@]+|[\w.\-@][\w.\/\-@]*)\s*$/;

/** Detect bash commands that are doing file write operations (write/append/redirect/heredoc). */
const BASH_FILE_WRITE_RE = /^\s*(cat|echo|printf)\b.*(?:>>?|<<)\s*/;

/**
 * Primary argument keys that identify the *target* of a tool call.
 * Used for fuzzy doom loop detection -- ignoring secondary/optional args.
 */
const PRIMARY_KEYS = ['path', 'file_path', 'command', 'pattern', 'query', 'url', 'content', 'filename', 'offset', 'limit'];

// =============================================================================
// PROMPT TEMPLATES
// =============================================================================

/**
 * Doom loop prompt - injected when same tool called repeatedly.
 */
export const DOOM_LOOP_PROMPT = (tool: string, count: number) => {
  if (count >= 6) {
    return `[System] CRITICAL: You've called ${tool} with the same arguments ${count} times. You are in a doom loop. You MUST:
1. STOP calling ${tool} immediately
2. Explain what you're stuck on
3. Try a completely different approach
Further identical calls will be rejected.`;
  }
  if (count >= 4) {
    return `[System] WARNING: You've called ${tool} ${count} times with identical arguments. This is a stuck state.
1. Try a DIFFERENT approach or tool
2. If blocked, explain the blocker`;
  }
  return `[System] You've called ${tool} with the same arguments ${count} times. This indicates a stuck state. Either:
1. Try a DIFFERENT approach or tool
2. If blocked, explain what's preventing progress
3. If the task is complete, say so explicitly`;
};

/**
 * Global doom loop prompt - injected when the same tool call is repeated across multiple workers.
 */
export const GLOBAL_DOOM_LOOP_PROMPT = (tool: string, workerCount: number, totalCalls: number) =>
  `[System] GLOBAL DOOM LOOP: ${totalCalls} calls to ${tool} across ${workerCount} workers. The entire swarm is stuck on this approach.
1. Try a fundamentally different strategy
2. Do NOT retry the same tool/parameters
3. Consider whether the task goal itself needs re-evaluation`;

/**
 * Test-fix rethink prompt - injected after consecutive test failures.
 */
export const TEST_FIX_RETHINK_PROMPT = (failures: number) =>
`[System] You've had ${failures} consecutive test failures. Step back and rethink:
1. Re-read the error messages carefully
2. Consider whether your approach is fundamentally wrong
3. Try a DIFFERENT fix strategy instead of iterating on the same one
Do not retry the same fix. Try a new approach.`;

/** Check whether a bash command is attempting file operations that should use dedicated tools. */
export function isBashFileOperation(command: string): boolean {
  return BASH_FILE_READ_RE.test(command) || BASH_FILE_WRITE_RE.test(command) || /heredoc|EOF/i.test(command);
}

export const BASH_FAILURE_CASCADE_PROMPT = (failures: number, lastCommand?: string) => {
  const isFileOp = lastCommand && isBashFileOperation(lastCommand);
  if (isFileOp) {
    return `[System] ${failures} consecutive bash commands have failed trying to do file operations.
STOP using bash for file operations. Use the correct tool:
- To CREATE a file: write_file (not cat/echo with redirect)
- To MODIFY a file: edit_file (not sed/awk)
- To READ a file: read_file (not cat/head/tail)
Switch to the correct tool NOW.`;
  }
  return `[System] ${failures} consecutive bash commands have failed. STOP and:
1. Explain what you're trying to accomplish
2. Try a DIFFERENT approach or tool
3. Do not run another bash command with the same pattern`;
};

export const SUMMARY_LOOP_PROMPT =
`[System] You've produced text-only responses without using tools. You should be DOING work, not summarizing it.
Pick the most important remaining task and start working on it NOW using your tools (write_file, edit_file, bash, etc.).
Do NOT output another status summary or task list.`;

// =============================================================================
// HELPER FUNCTIONS (exported for external use)
// =============================================================================

/**
 * Extract success and output from a bash tool result.
 * In production, bash results are objects `{ success, output, metadata }`.
 * Tests may pass strings directly. This normalizes both.
 */
export function extractBashResult(result: unknown): { success: boolean; output: string } {
  if (result && typeof result === 'object') {
    const obj = result as Record<string, unknown>;
    return {
      success: obj.success !== false,
      output: typeof obj.output === 'string' ? obj.output : '',
    };
  }
  if (typeof result === 'string') {
    return { success: true, output: result };
  }
  return { success: true, output: '' };
}

/**
 * Extract the file target from a simple bash file-read command.
 * Returns null for complex commands (pipes, redirects, non-file-read commands).
 * Used to normalize doom loop fingerprints across cat/head/tail/wc targeting the same file.
 */
export function extractBashFileTarget(command: string): string | null {
  if (/[|;&<>]/.test(command)) return null; // pipes/redirects = complex, skip
  const match = command.match(BASH_FILE_READ_RE);
  return match ? match[2] : null;
}

/**
 * Compute a structural fingerprint for a tool call.
 * Extracts only the primary argument (path, command, pattern, query) and ignores
 * secondary arguments (encoding, timeout, flags). This catches near-identical calls
 * that differ only in optional parameters.
 */
export function computeToolFingerprint(toolName: string, argsStr: string): string {
  try {
    const args = JSON.parse(argsStr || '{}') as Record<string, unknown>;

    // W1: Normalize bash file-read commands so cat/head/tail/wc targeting the same file
    // produce the same fingerprint, triggering doom loop detection.
    if (toolName === 'bash' && typeof args.command === 'string') {
      const fileTarget = extractBashFileTarget(args.command);
      if (fileTarget) return `bash:file_read:${fileTarget}`;
    }

    const primaryArgs: Record<string, unknown> = {};
    for (const key of PRIMARY_KEYS) {
      if (key in args) {
        primaryArgs[key] = args[key];
      }
    }

    // If no primary keys found, fall back to full args
    if (Object.keys(primaryArgs).length === 0) {
      return `${toolName}:${stableStringify(args)}`;
    }

    return `${toolName}:${stableStringify(primaryArgs)}`;
  } catch {
    // If args can't be parsed, use raw string
    return `${toolName}:${argsStr}`;
  }
}

// =============================================================================
// LOOP DETECTOR CLASS
// =============================================================================

/**
 * Recent tool call entry for loop detection.
 */
export interface RecentToolCall {
  tool: string;
  args: string;
  timestamp: number;
}

/**
 * LoopDetector handles doom loop detection and pattern-based stuck state identification.
 *
 * Two-tier detection:
 * 1. Exact match: same tool+args string (threshold: 3 by default)
 * 2. Fuzzy match: same tool + same primary args, ignoring optional params (threshold: 4 by default)
 */
export class LoopDetector {
  private loopState: LoopDetectionState;

  constructor(tuning?: EconomicsTuning) {
    this.loopState = {
      doomLoopDetected: false,
      lastTool: null,
      consecutiveCount: 0,
      threshold: tuning?.doomLoopThreshold ?? 3,
      fuzzyThreshold: tuning?.doomLoopFuzzyThreshold ?? (tuning?.doomLoopThreshold ? tuning.doomLoopThreshold + 1 : 4),
      lastWarningTime: 0,
    };
  }

  /**
   * Update doom loop detection state given recent tool calls.
   * Returns true if a NEW doom loop was just detected (first time).
   */
  updateDoomLoopState(toolName: string, argsStr: string, recentCalls: RecentToolCall[]): boolean {
    const currentCall = `${toolName}:${argsStr}`;

    // === EXACT MATCH: Count consecutive identical calls from the end ===
    let consecutiveCount = 0;
    for (let i = recentCalls.length - 1; i >= 0; i--) {
      const call = recentCalls[i];
      if (`${call.tool}:${call.args}` === currentCall) {
        consecutiveCount++;
      } else {
        break;
      }
    }

    // === FUZZY MATCH: Catches near-identical calls that differ only in optional params ===
    // Only check if exact match didn't already trigger
    if (consecutiveCount < this.loopState.threshold) {
      const currentFingerprint = computeToolFingerprint(toolName, argsStr);
      let fuzzyCount = 0;
      for (let i = recentCalls.length - 1; i >= 0; i--) {
        const call = recentCalls[i];
        const callFingerprint = computeToolFingerprint(call.tool, call.args);
        if (callFingerprint === currentFingerprint) {
          fuzzyCount++;
        } else {
          break;
        }
      }
      // Use fuzzy count if it exceeds the fuzzy threshold
      if (fuzzyCount >= this.loopState.fuzzyThreshold) {
        consecutiveCount = Math.max(consecutiveCount, fuzzyCount);
      }
    }

    this.loopState.consecutiveCount = consecutiveCount;
    this.loopState.lastTool = toolName;

    // Detect doom loop when threshold reached
    const wasDoomLoop = this.loopState.doomLoopDetected;
    this.loopState.doomLoopDetected = consecutiveCount >= this.loopState.threshold;

    // Return true when doom loop first detected (not on every check)
    return this.loopState.doomLoopDetected && !wasDoomLoop;
  }

  /**
   * Get the current loop detection state (copy).
   */
  getState(): LoopDetectionState {
    return { ...this.loopState };
  }

  /**
   * Whether a doom loop is currently detected.
   */
  get isDoomLoop(): boolean {
    return this.loopState.doomLoopDetected;
  }

  /**
   * The tool that is currently being repeated.
   */
  get lastTool(): string | null {
    return this.loopState.lastTool;
  }

  /**
   * How many consecutive times the same call has been made.
   */
  get consecutiveCount(): number {
    return this.loopState.consecutiveCount;
  }

  /**
   * Reset the loop detection state (preserves tuning thresholds).
   */
  reset(tuning?: EconomicsTuning): void {
    this.loopState = {
      doomLoopDetected: false,
      lastTool: null,
      consecutiveCount: 0,
      threshold: tuning?.doomLoopThreshold ?? 3,
      fuzzyThreshold: tuning?.doomLoopFuzzyThreshold ?? (tuning?.doomLoopThreshold ? tuning.doomLoopThreshold + 1 : 4),
      lastWarningTime: 0,
    };
  }

  /**
   * Check if recent tool calls indicate a stuck state (same call 3x in a row).
   */
  isStuckByRepetition(recentCalls: RecentToolCall[]): boolean {
    if (recentCalls.length >= 3) {
      const last3 = recentCalls.slice(-3);
      const unique = new Set(last3.map(tc => `${tc.tool}:${tc.args}`));
      if (unique.size === 1) {
        return true;
      }
    }
    return false;
  }

  /**
   * Extract the last bash command from recent tool calls (for remediation prompts).
   */
  extractLastBashCommand(recentCalls: RecentToolCall[]): string | undefined {
    for (let i = recentCalls.length - 1; i >= 0; i--) {
      if (recentCalls[i].tool === 'bash') {
        try {
          const parsed = JSON.parse(recentCalls[i].args);
          return parsed.command;
        } catch { /* ignore parse errors */ }
        break;
      }
    }
    return undefined;
  }
}
