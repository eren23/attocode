/**
 * Trick: JSON Utilities
 *
 * Robust JSON parsing utilities that handle:
 * - Nested objects (the regex `\{[^}]*\}` problem)
 * - Strings containing braces
 * - Escaped quotes
 * - Malformed JSON with recovery
 * - LLM response extraction (code blocks, tool calls)
 */

// =============================================================================
// TYPES
// =============================================================================

export interface SafeParseOptions {
  /** Context for error messages (e.g., "tool read_file") */
  context?: string;
  /** Whether to attempt recovery from malformed JSON */
  attemptRecovery?: boolean;
}

export interface SafeParseResult<T = unknown> {
  success: boolean;
  value?: T;
  error?: string;
  /** Whether recovery was applied */
  recovered?: boolean;
}

export interface ToolCall {
  tool: string;
  input: Record<string, unknown>;
}

// =============================================================================
// CORE: EXTRACT JSON OBJECT
// =============================================================================

/**
 * Extract a complete JSON object from text using brace-depth tracking.
 *
 * Unlike regex `\{[^}]*\}`, this properly handles:
 * - Nested objects: `{"a": {"b": 1}}`
 * - Nested arrays: `{"a": [1, [2, 3]]}`
 * - Strings containing braces: `{"text": "hello { } world"}`
 * - Escaped quotes: `{"text": "he said \"hi\""}`
 *
 * @param text - The text to search for JSON
 * @param startFrom - Optional index to start searching from
 * @returns The extracted JSON string and its end index, or null if not found
 */
export function extractJsonObject(
  text: string,
  startFrom = 0,
): { json: string; endIndex: number } | null {
  // Find the first `{`
  const start = text.indexOf('{', startFrom);
  if (start === -1) return null;

  let depth = 0;
  let inString = false;
  let escape = false;

  for (let i = start; i < text.length; i++) {
    const char = text[i];

    // Handle escape sequences inside strings
    if (escape) {
      escape = false;
      continue;
    }

    if (char === '\\' && inString) {
      escape = true;
      continue;
    }

    // Toggle string state on unescaped quotes
    if (char === '"') {
      inString = !inString;
      continue;
    }

    // Only count braces outside of strings
    if (!inString) {
      if (char === '{' || char === '[') depth++;
      if (char === '}' || char === ']') depth--;

      if (depth === 0) {
        // Found complete JSON object
        return {
          json: text.slice(start, i + 1),
          endIndex: i + 1,
        };
      }
    }
  }

  // Incomplete JSON (unclosed braces)
  return null;
}

/**
 * Extract all JSON objects from text.
 */
export function extractAllJsonObjects(text: string): string[] {
  const results: string[] = [];
  let position = 0;

  while (position < text.length) {
    const extracted = extractJsonObject(text, position);
    if (!extracted) break;

    results.push(extracted.json);
    position = extracted.endIndex;
  }

  return results;
}

// =============================================================================
// SAFE PARSE: MULTI-LEVEL FALLBACK
// =============================================================================

/**
 * Safely parse JSON with multi-level fallback and recovery.
 *
 * Fallback levels:
 * 1. Direct JSON.parse
 * 2. Extract JSON object from surrounding text
 * 3. Attempt malformed JSON recovery (if enabled)
 *
 * @param input - Raw input (may be JSON or text containing JSON)
 * @param options - Parsing options
 */
export function safeParseJson<T = unknown>(
  input: string,
  options: SafeParseOptions = {},
): SafeParseResult<T> {
  const { context, attemptRecovery = true } = options;

  if (!input || typeof input !== 'string') {
    return {
      success: false,
      error: `Invalid input${context ? ` for ${context}` : ''}: expected string`,
    };
  }

  const trimmed = input.trim();

  // Level 1: Direct parse
  try {
    const value = JSON.parse(trimmed) as T;
    return { success: true, value };
  } catch {
    // Continue to fallbacks
  }

  // Level 2: Extract JSON object from text
  const extracted = extractJsonObject(trimmed);
  if (extracted) {
    try {
      const value = JSON.parse(extracted.json) as T;
      return { success: true, value };
    } catch {
      // Continue to recovery
    }
  }

  // Level 3: Attempt recovery (if enabled)
  if (attemptRecovery) {
    const recovered = attemptJsonRecovery(trimmed);
    if (recovered) {
      try {
        const value = JSON.parse(recovered) as T;
        return { success: true, value, recovered: true };
      } catch {
        // Recovery failed
      }
    }
  }

  return {
    success: false,
    error: `Failed to parse JSON${context ? ` for ${context}` : ''}: ${trimmed.slice(0, 50)}...`,
  };
}

/**
 * Attempt to recover malformed JSON.
 *
 * Handles common issues:
 * - Trailing commas: `{"a": 1,}`
 * - Single quotes: `{'a': 1}`
 * - Unquoted keys: `{a: 1}`
 * - Missing quotes on string values: `{"a": hello}`
 */
function attemptJsonRecovery(input: string): string | null {
  let fixed = input;

  // Remove trailing commas before } or ]
  fixed = fixed.replace(/,(\s*[}\]])/g, '$1');

  // Replace single quotes with double quotes (simple cases only)
  // This is intentionally conservative to avoid breaking strings with apostrophes
  if (fixed.includes("'") && !fixed.includes('"')) {
    fixed = fixed.replace(/'/g, '"');
  }

  // Try to quote unquoted keys: {foo: 1} -> {"foo": 1}
  fixed = fixed.replace(/\{(\s*)([a-zA-Z_][a-zA-Z0-9_]*)(\s*):/g, '{$1"$2"$3:');
  fixed = fixed.replace(/,(\s*)([a-zA-Z_][a-zA-Z0-9_]*)(\s*):/g, ',$1"$2"$3:');

  // Only return if something changed
  return fixed !== input ? fixed : null;
}

// =============================================================================
// TOOL CALL EXTRACTION
// =============================================================================

/**
 * Extract a tool call from an LLM response.
 *
 * Handles multiple formats:
 * - Code block: ```json\n{"tool": "x", "input": {...}}\n```
 * - Inline JSON: {"tool": "x", "input": {...}}
 * - Nested inputs: {"tool": "x", "input": {"a": {"b": 1}}}
 *
 * @param response - The LLM response text
 * @returns The extracted tool call, or null if not found
 */
export function extractToolCallJson(response: string): ToolCall | null {
  // Try code block first (most common format)
  const codeBlockPatterns = [/```json\s*([\s\S]*?)```/, /```\s*([\s\S]*?)```/];

  for (const pattern of codeBlockPatterns) {
    const match = response.match(pattern);
    if (match) {
      const result = parseToolCallObject(match[1]);
      if (result) return result;
    }
  }

  // Try extracting raw JSON from the response
  const extracted = extractJsonObject(response);
  if (extracted) {
    const result = parseToolCallObject(extracted.json);
    if (result) return result;
  }

  return null;
}

/**
 * Parse a potential tool call object.
 */
function parseToolCallObject(text: string): ToolCall | null {
  const result = safeParseJson<Record<string, unknown>>(text, {
    context: 'tool call',
  });

  if (!result.success || !result.value) return null;

  const obj = result.value;

  // Validate tool call structure
  if (typeof obj.tool !== 'string') return null;

  return {
    tool: obj.tool,
    input: (obj.input as Record<string, unknown>) ?? {},
  };
}

/**
 * Extract multiple tool calls from a response.
 */
export function extractAllToolCalls(response: string): ToolCall[] {
  const results: ToolCall[] = [];

  // Try code blocks first
  const codeBlockPattern = /```(?:json)?\s*([\s\S]*?)```/g;
  let match;

  while ((match = codeBlockPattern.exec(response)) !== null) {
    const result = parseToolCallObject(match[1]);
    if (result) results.push(result);
  }

  // If no code blocks found tool calls, try raw JSON objects
  if (results.length === 0) {
    const jsonObjects = extractAllJsonObjects(response);
    for (const json of jsonObjects) {
      const result = parseToolCallObject(json);
      if (result) results.push(result);
    }
  }

  return results;
}
