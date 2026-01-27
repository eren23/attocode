/**
 * Lesson 8: Input Structuring Patterns
 *
 * Patterns and utilities for structuring inputs to reduce LLM mistakes.
 * These patterns address common failure modes in agent systems.
 */

import type { ToolResult } from './types.js';

// =============================================================================
// COMMON LLM MISTAKES & FIXES
// =============================================================================

/**
 * ═══════════════════════════════════════════════════════════════════════════
 * INPUT STRUCTURING: Why It Matters
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * LLMs make predictable mistakes. Good input structuring prevents them:
 *
 * MISTAKE 1: Hallucinating Tool Results
 *   Bad:  "Read the config file and tell me the port"
 *   LLM:  "The config probably has port: 3000..." (makes up content)
 *   Fix:  Clear instruction to WAIT for actual result
 *
 * MISTAKE 2: Forgetting Previous Actions
 *   After 10 turns, LLM might re-read files it already read
 *   Fix:  State summary at conversation start
 *
 * MISTAKE 3: Ambiguous Tool Results
 *   Tool output blends into conversation, LLM gets confused
 *   Fix:  Clear delimiters around tool results
 *
 * MISTAKE 4: Over-Planning Before Acting
 *   LLM creates elaborate 10-step plans, then fails on step 2
 *   Fix:  Encourage incremental progress
 * ═══════════════════════════════════════════════════════════════════════════
 */

// =============================================================================
// TOOL RESULT FORMATTING
// =============================================================================

/**
 * Format a tool result with clear boundaries.
 *
 * Clear formatting helps the LLM:
 * 1. Distinguish tool output from conversation
 * 2. Understand success/failure status
 * 3. Parse structured data correctly
 */
export function formatToolResult(toolName: string, result: ToolResult): string {
  const header = `═══ TOOL: ${toolName} ═══`;
  const footer = '═'.repeat(header.length);
  const status = result.success ? '✓ Success' : '✗ Failed';

  return `${header}\n${status}\n\n${result.output}\n${footer}`;
}

/**
 * Format multiple tool results.
 */
export function formatToolResults(
  results: Array<{ name: string; result: ToolResult }>
): string {
  return results.map(r => formatToolResult(r.name, r.result)).join('\n\n');
}

// =============================================================================
// STATE TRACKING
// =============================================================================

/**
 * State summary for long conversations.
 */
export interface ConversationStateSummary {
  filesRead: string[];
  filesModified: string[];
  commandsRun: string[];
  currentTask: string;
  completedSteps: string[];
  pendingSteps: string[];
}

/**
 * Build a state summary string for the LLM.
 *
 * Insert this at the start of conversations to help the LLM
 * remember what has been done.
 */
export function buildStateSummary(state: Partial<ConversationStateSummary>): string {
  const sections: string[] = ['[CONVERSATION STATE]'];

  if (state.currentTask) {
    sections.push(`Current Task: ${state.currentTask}`);
  }

  if (state.filesRead?.length) {
    sections.push(`Files Read: ${state.filesRead.join(', ')}`);
  }

  if (state.filesModified?.length) {
    sections.push(`Files Modified: ${state.filesModified.join(', ')}`);
  }

  if (state.commandsRun?.length) {
    sections.push(`Commands Run: ${state.commandsRun.join(', ')}`);
  }

  if (state.completedSteps?.length) {
    sections.push(`Completed: ${state.completedSteps.join(' → ')}`);
  }

  if (state.pendingSteps?.length) {
    sections.push(`Remaining: ${state.pendingSteps.join(' → ')}`);
  }

  sections.push('[END STATE]');

  return sections.join('\n');
}

// =============================================================================
// INSTRUCTION PATTERNS
// =============================================================================

/**
 * Instruction templates that reduce common mistakes.
 */
export const INSTRUCTION_PATTERNS = {
  /**
   * Prevent hallucinating tool results.
   */
  WAIT_FOR_RESULT: `
IMPORTANT: When you use a tool, WAIT for the actual result.
Do not imagine, guess, or assume what the result will be.
The system will provide the real output.
`.trim(),

  /**
   * Encourage incremental progress.
   */
  ONE_STEP_AT_A_TIME: `
Work incrementally:
1. Take ONE action
2. Observe the result
3. Decide the next action based on what you learned
Do not plan multiple steps ahead - the situation may change.
`.trim(),

  /**
   * Guide edit operations.
   */
  EDIT_GUIDANCE: `
When editing files:
1. ALWAYS read the file first to see current contents
2. Use edit_file with EXACT string matching (copy-paste from read result)
3. Include enough context in old_string to make it unique
4. If edit fails, read the file again - it may have changed
`.trim(),

  /**
   * Handle errors gracefully.
   */
  ERROR_RECOVERY: `
If a tool fails:
1. Read the error message carefully
2. Consider what went wrong (wrong path? permission? syntax?)
3. Try an alternative approach
4. If stuck after 2-3 attempts, explain the issue
`.trim(),

  /**
   * Complete tasks explicitly.
   */
  COMPLETION_SIGNAL: `
When the task is complete:
- Summarize what was done
- List any files created or modified
- Note any issues encountered
- Do NOT use any more tools after completing
`.trim(),
} as const;

/**
 * Build a comprehensive system prompt with anti-mistake patterns.
 */
export function buildRobustSystemPrompt(
  toolDescriptions: string,
  additionalInstructions?: string
): string {
  return `You are a coding assistant with access to file and command tools.

## Available Tools
${toolDescriptions}

## Tool Usage Rules
${INSTRUCTION_PATTERNS.WAIT_FOR_RESULT}

${INSTRUCTION_PATTERNS.ONE_STEP_AT_A_TIME}

${INSTRUCTION_PATTERNS.EDIT_GUIDANCE}

${INSTRUCTION_PATTERNS.ERROR_RECOVERY}

## Completion
${INSTRUCTION_PATTERNS.COMPLETION_SIGNAL}

${additionalInstructions ? `## Additional Instructions\n${additionalInstructions}` : ''}
`.trim();
}

// =============================================================================
// INPUT VALIDATION HELPERS
// =============================================================================

/**
 * Sanitize file paths in user input.
 * Helps prevent common path-related mistakes.
 */
export function sanitizePath(path: string): string {
  return path
    .trim()
    .replace(/^['"`]|['"`]$/g, '') // Remove quotes
    .replace(/\\\\/g, '/') // Normalize Windows paths
    .replace(/\/+/g, '/'); // Remove duplicate slashes
}

/**
 * Extract file paths mentioned in text.
 * Useful for pre-loading context.
 */
export function extractFilePaths(text: string): string[] {
  // Match common file path patterns
  const patterns = [
    /`([^`]+\.[a-z]{1,4})`/gi, // `file.ext`
    /['"]([^'"]+\.[a-z]{1,4})['"]/gi, // 'file.ext' or "file.ext"
    /\b((?:\.\/|\.\.\/|\/)?(?:[\w-]+\/)*[\w-]+\.[a-z]{1,4})\b/gi, // bare paths
  ];

  const paths = new Set<string>();

  for (const pattern of patterns) {
    let match;
    while ((match = pattern.exec(text)) !== null) {
      const path = sanitizePath(match[1]);
      if (path && !path.includes(' ')) {
        paths.add(path);
      }
    }
  }

  return Array.from(paths);
}

/**
 * Detect if user input is asking to do something dangerous.
 * Returns warnings for the agent to consider.
 */
export function detectDangerousIntent(input: string): string[] {
  const warnings: string[] = [];
  const lower = input.toLowerCase();

  if (lower.includes('delete') && (lower.includes('all') || lower.includes('everything'))) {
    warnings.push('Request involves bulk deletion - proceed with caution');
  }

  if (lower.includes('production') || lower.includes('prod')) {
    warnings.push('Request mentions production environment');
  }

  if (lower.includes('password') || lower.includes('secret') || lower.includes('api key')) {
    warnings.push('Request involves sensitive credentials');
  }

  if (lower.includes('recursive') && lower.includes('delete')) {
    warnings.push('Recursive deletion requested');
  }

  return warnings;
}

// =============================================================================
// RESPONSE PARSING HELPERS
// =============================================================================

/**
 * Check if LLM response indicates task completion.
 */
export function isCompletionResponse(response: string): boolean {
  const completionIndicators = [
    /task (is )?(now )?complete/i,
    /i('ve| have) (finished|completed|done)/i,
    /successfully (completed|finished|done)/i,
    /all (steps|tasks) (are )?(now )?(complete|done)/i,
  ];

  return completionIndicators.some(pattern => pattern.test(response));
}

/**
 * Check if LLM response indicates it's stuck or confused.
 */
export function isStuckResponse(response: string): boolean {
  const stuckIndicators = [
    /i('m| am) (not sure|unsure|confused)/i,
    /i (don't|do not) (know|understand)/i,
    /could you (please )?(clarify|explain)/i,
    /what (do you mean|should i do)/i,
    /i('m| am) stuck/i,
  ];

  return stuckIndicators.some(pattern => pattern.test(response));
}

/**
 * Extract a summary from an LLM response.
 * Useful for displaying concise status updates.
 */
export function extractSummary(response: string, maxLength = 200): string {
  // Try to find a summary section
  const summaryMatch = response.match(/(?:summary|result|completed?):?\s*(.+?)(?:\n\n|$)/i);
  if (summaryMatch) {
    return truncate(summaryMatch[1], maxLength);
  }

  // Otherwise, take the first paragraph
  const firstPara = response.split('\n\n')[0];
  return truncate(firstPara, maxLength);
}

function truncate(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text;
  return text.slice(0, maxLength - 3) + '...';
}
