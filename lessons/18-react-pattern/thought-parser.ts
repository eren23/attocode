/**
 * Lesson 18: Thought Parser
 *
 * Parses LLM output to extract ReAct components:
 * - Thought: The reasoning
 * - Action: The tool call
 * - Final Answer: The conclusion
 *
 * USER CONTRIBUTION OPPORTUNITY:
 * The parsing logic below handles common formats, but you could
 * implement more robust parsing with:
 * - Fuzzy matching for malformed output
 * - Multiple action formats (JSON, function call, natural language)
 * - Recovery strategies for partial matches
 */

import type {
  ParsedReActOutput,
  ReActAction,
  ReActPatterns,
} from './types.js';

// =============================================================================
// DEFAULT PATTERNS
// =============================================================================

const defaultPatterns: ReActPatterns = {
  thought: /Thought:\s*(.+?)(?=Action:|Final Answer:|$)/is,
  action: /Action:\s*(.+?)(?=Observation:|Thought:|Final Answer:|$)/is,
  finalAnswer: /Final Answer:\s*(.+?)$/is,
  toolName: /^(\w+)\s*[\(\{]/,
  toolArgs: /[\(\{](.+)[\)\}]$/s,
};

// =============================================================================
// MAIN PARSER
// =============================================================================

/**
 * Parse LLM output for ReAct format.
 *
 * @param output - Raw LLM output
 * @param patterns - Optional custom patterns
 * @returns Parsed ReAct output
 */
export function parseReActOutput(
  output: string,
  patterns: ReActPatterns = defaultPatterns
): ParsedReActOutput {
  const errors: string[] = [];
  const trimmedOutput = output.trim();

  // Check for final answer first
  const finalAnswerMatch = trimmedOutput.match(patterns.finalAnswer);
  if (finalAnswerMatch) {
    return {
      success: true,
      isFinalAnswer: true,
      finalAnswer: finalAnswerMatch[1].trim(),
      errors: [],
      raw: output,
    };
  }

  // Extract thought
  const thoughtMatch = trimmedOutput.match(patterns.thought);
  const thought = thoughtMatch ? thoughtMatch[1].trim() : undefined;

  if (!thought) {
    errors.push('Could not extract thought from output');
  }

  // Extract action
  const actionMatch = trimmedOutput.match(patterns.action);
  let action: ReActAction | undefined;

  if (actionMatch) {
    const actionStr = actionMatch[1].trim();
    const parsedAction = parseAction(actionStr);

    if (parsedAction.success) {
      action = parsedAction.action;
    } else {
      errors.push(...parsedAction.errors);
    }
  } else {
    errors.push('Could not extract action from output');
  }

  // Determine success
  const success = errors.length === 0 && !!thought && !!action;

  return {
    success,
    thought,
    action,
    isFinalAnswer: false,
    errors,
    raw: output,
  };
}

// =============================================================================
// ACTION PARSING
// =============================================================================

/**
 * Parse an action string into a ReActAction.
 */
function parseAction(
  actionStr: string
): { success: boolean; action?: ReActAction; errors: string[] } {
  const errors: string[] = [];

  // Try different formats

  // Format 1: tool_name({"arg": "value"})
  const funcCallMatch = actionStr.match(/^(\w+)\s*\((.+)\)$/s);
  if (funcCallMatch) {
    const toolName = funcCallMatch[1];
    const argsStr = funcCallMatch[2].trim();

    try {
      const args = JSON.parse(argsStr);
      return {
        success: true,
        action: { tool: toolName, args, raw: actionStr },
        errors: [],
      };
    } catch {
      errors.push(`Could not parse arguments as JSON: ${argsStr}`);
    }
  }

  // Format 2: tool_name {"arg": "value"}
  const spaceMatch = actionStr.match(/^(\w+)\s+(\{.+\})$/s);
  if (spaceMatch) {
    const toolName = spaceMatch[1];
    const argsStr = spaceMatch[2].trim();

    try {
      const args = JSON.parse(argsStr);
      return {
        success: true,
        action: { tool: toolName, args, raw: actionStr },
        errors: [],
      };
    } catch {
      errors.push(`Could not parse arguments as JSON: ${argsStr}`);
    }
  }

  // Format 3: tool_name: {"arg": "value"}
  const colonMatch = actionStr.match(/^(\w+):\s*(\{.+\})$/s);
  if (colonMatch) {
    const toolName = colonMatch[1];
    const argsStr = colonMatch[2].trim();

    try {
      const args = JSON.parse(argsStr);
      return {
        success: true,
        action: { tool: toolName, args, raw: actionStr },
        errors: [],
      };
    } catch {
      errors.push(`Could not parse arguments as JSON: ${argsStr}`);
    }
  }

  // Format 4: Just tool name (no args)
  const simpleMatch = actionStr.match(/^(\w+)$/);
  if (simpleMatch) {
    return {
      success: true,
      action: { tool: simpleMatch[1], args: {}, raw: actionStr },
      errors: [],
    };
  }

  // Format 5: tool_name arg1=value1 arg2=value2
  const kvMatch = actionStr.match(/^(\w+)\s+(.+)$/);
  if (kvMatch) {
    const toolName = kvMatch[1];
    const argsStr = kvMatch[2];
    const args = parseKeyValueArgs(argsStr);

    if (Object.keys(args).length > 0) {
      return {
        success: true,
        action: { tool: toolName, args, raw: actionStr },
        errors: [],
      };
    }
  }

  // Couldn't parse
  errors.push(`Unrecognized action format: ${actionStr}`);

  return { success: false, errors };
}

/**
 * Parse key=value style arguments.
 */
function parseKeyValueArgs(argsStr: string): Record<string, unknown> {
  const args: Record<string, unknown> = {};
  const pattern = /(\w+)\s*=\s*("([^"]*)"|'([^']*)'|(\S+))/g;
  let match;

  while ((match = pattern.exec(argsStr)) !== null) {
    const key = match[1];
    const value = match[3] ?? match[4] ?? match[5];
    args[key] = value;
  }

  return args;
}

// =============================================================================
// EXTRACTION HELPERS
// =============================================================================

/**
 * Extract all thoughts from a multi-step response.
 */
export function extractAllThoughts(output: string): string[] {
  const thoughts: string[] = [];
  const pattern = /Thought:\s*(.+?)(?=Action:|Final Answer:|Thought:|$)/gis;
  let match;

  while ((match = pattern.exec(output)) !== null) {
    thoughts.push(match[1].trim());
  }

  return thoughts;
}

/**
 * Extract all actions from a multi-step response.
 */
export function extractAllActions(output: string): string[] {
  const actions: string[] = [];
  const pattern = /Action:\s*(.+?)(?=Observation:|Thought:|Final Answer:|$)/gis;
  let match;

  while ((match = pattern.exec(output)) !== null) {
    actions.push(match[1].trim());
  }

  return actions;
}

/**
 * Check if output contains a final answer.
 */
export function hasFinalAnswer(output: string): boolean {
  return /Final Answer:/i.test(output);
}

/**
 * Extract the final answer from output.
 */
export function extractFinalAnswer(output: string): string | null {
  const match = output.match(/Final Answer:\s*(.+?)$/is);
  return match ? match[1].trim() : null;
}

// =============================================================================
// VALIDATION
// =============================================================================

/**
 * Validate that a parsed action has required fields.
 */
export function validateAction(
  action: ReActAction,
  availableTools: string[]
): { valid: boolean; errors: string[] } {
  const errors: string[] = [];

  if (!action.tool) {
    errors.push('Action missing tool name');
  } else if (!availableTools.includes(action.tool)) {
    errors.push(`Unknown tool: ${action.tool}. Available: ${availableTools.join(', ')}`);
  }

  if (action.args === undefined) {
    errors.push('Action missing arguments');
  }

  return { valid: errors.length === 0, errors };
}

/**
 * Attempt to fix common parsing issues.
 */
export function attemptRecovery(
  output: string,
  availableTools: string[]
): ParsedReActOutput | null {
  // Try to find a tool name anywhere in the output
  for (const tool of availableTools) {
    const toolPattern = new RegExp(`\\b${tool}\\b`, 'i');
    if (toolPattern.test(output)) {
      // Found a tool name, try to extract around it
      const argsPattern = new RegExp(`${tool}[\\s\\(\\{:]+(.+?)(?:\\)|\\}|$)`, 'is');
      const argsMatch = output.match(argsPattern);

      if (argsMatch) {
        try {
          // Try to parse as JSON
          const argsStr = argsMatch[1].trim();
          const args = argsStr.startsWith('{')
            ? JSON.parse(argsStr.endsWith('}') ? argsStr : argsStr + '}')
            : {};

          return {
            success: true,
            thought: 'Recovered from malformed output',
            action: { tool, args, raw: output },
            isFinalAnswer: false,
            errors: ['Used recovery parsing'],
            raw: output,
          };
        } catch {
          // Continue trying
        }
      }
    }
  }

  return null;
}

// =============================================================================
// EXPORTS
// =============================================================================

export { defaultPatterns };
