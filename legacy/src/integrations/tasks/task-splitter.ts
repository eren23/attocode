/**
 * Task Splitter — LLM-driven splitting logic for task decomposition.
 *
 * Extracted from smart-decomposer.ts (Phase 3e).
 * Contains: prompt building, response parsing, JSON repair,
 * natural language extraction, and decomposition validation.
 */

import type {
  SubtaskType,
  DecomposeContext,
  LLMDecomposeResult,
  SmartDecompositionResult,
} from './smart-decomposer.js';

// =============================================================================
// DECOMPOSITION VALIDATION
// =============================================================================

export interface DecompositionValidationResult {
  valid: boolean;
  issues: string[];
  warnings: string[];
}

/**
 * F5: Validate a decomposition result for structural correctness, feasibility, and granularity.
 *
 * Checks:
 * 1. Structural: no cycles, valid dependency refs, each subtask has description
 * 2. Feasibility: referenced files exist (warning only)
 * 3. Granularity: no subtask complexity > 7 (should split further)
 */
export function validateDecomposition(
  result: SmartDecompositionResult,
): DecompositionValidationResult {
  const issues: string[] = [];
  const warnings: string[] = [];
  const taskIds = new Set(result.subtasks.map((s) => s.id));

  // 1. Structural checks
  // Cycle detection
  if (result.dependencyGraph.cycles.length > 0) {
    for (const cycle of result.dependencyGraph.cycles) {
      issues.push(`Dependency cycle detected: ${cycle.join(' \u2192 ')}`);
    }
  }

  // Valid dependency references
  for (const subtask of result.subtasks) {
    for (const dep of subtask.dependencies) {
      if (!taskIds.has(dep)) {
        issues.push(`Task ${subtask.id} references non-existent dependency: ${dep}`);
      }
      if (dep === subtask.id) {
        issues.push(`Task ${subtask.id} depends on itself`);
      }
    }
    // Each subtask must have a meaningful description
    if (!subtask.description || subtask.description.trim().length < 5) {
      issues.push(`Task ${subtask.id} has empty or trivial description`);
    }
  }

  // 2. Feasibility: check if referenced files exist (warnings only — files may be created by earlier tasks)
  for (const subtask of result.subtasks) {
    if (subtask.relevantFiles) {
      for (const file of subtask.relevantFiles) {
        try {
          const fs = require('node:fs');
          const path = require('node:path');
          if (!fs.existsSync(path.resolve(file))) {
            warnings.push(`Task ${subtask.id} references non-existent file: ${file}`);
          }
        } catch {
          // Can't check — skip
        }
      }
    }
  }

  // 3. Granularity: flag overly complex subtasks
  for (const subtask of result.subtasks) {
    if (subtask.complexity > 7) {
      warnings.push(
        `Task ${subtask.id} has complexity ${subtask.complexity} (>7) — consider splitting further`,
      );
    }
  }

  // Additional structural check: at least 2 subtasks
  if (result.subtasks.length < 2) {
    issues.push(
      `Decomposition produced only ${result.subtasks.length} subtask(s) — too few for swarm mode`,
    );
  }

  return {
    valid: issues.length === 0,
    issues,
    warnings,
  };
}

// =============================================================================
// PROMPT BUILDING
// =============================================================================

/**
 * Create an LLM prompt for task decomposition.
 */
export function createDecompositionPrompt(task: string, context: DecomposeContext): string {
  const parts = [
    'You are a task decomposition expert. Break down the following task into subtasks.',
    '',
    `Task: ${task}`,
    '',
  ];

  if (context.repoMap) {
    parts.push('Codebase context:');
    parts.push(`- ${context.repoMap.chunks.size} files`);
    parts.push(`- Entry points: ${context.repoMap.entryPoints.slice(0, 3).join(', ')}`);
    parts.push('');
  }

  if (context.hints && context.hints.length > 0) {
    parts.push('Hints:');
    for (const hint of context.hints) {
      parts.push(`- ${hint}`);
    }
    parts.push('');
  }

  parts.push('For each subtask, provide:');
  parts.push('1. Description');
  parts.push(
    '2. Type (research, analysis, design, implement, test, refactor, review, document, integrate, deploy, merge)',
  );
  parts.push('3. Complexity (1-10)');
  parts.push('4. Dependencies (which other subtasks must complete first)');
  parts.push('5. Whether it can run in parallel with other tasks');
  parts.push('');
  parts.push(
    'Also suggest an overall strategy: sequential, parallel, hierarchical, adaptive, or pipeline.',
  );
  parts.push('');
  parts.push('Respond in JSON format.');

  return parts.join('\n');
}

// =============================================================================
// JSON REPAIR
// =============================================================================

/**
 * Normalize a raw subtask object from JSON into a consistent shape.
 */
function normalizeSubtask(s: any): LLMDecomposeResult['subtasks'][number] {
  return {
    description: s.description || s.desc || s.title || s.name || '',
    type: s.type || s.task_type || s.category || 'implement',
    complexity: s.complexity || s.difficulty || 3,
    dependencies: s.dependencies || s.deps || s.depends_on || [],
    parallelizable: s.parallelizable ?? s.parallel ?? true,
    relevantFiles: s.relevantFiles || s.relevant_files || s.files,
    suggestedRole: s.suggestedRole || s.suggested_role || s.role,
  };
}

/**
 * Try to extract subtasks from a parsed JSON object/array.
 * Returns null if the structure doesn't contain usable subtask data.
 */
function extractSubtasksFromParsed(parsed: any): LLMDecomposeResult | null {
  // Handle array-at-root: some models return [{...}, {...}] instead of {"subtasks": [...]}
  if (Array.isArray(parsed)) {
    parsed = { subtasks: parsed, strategy: 'adaptive', reasoning: '(array-at-root)' };
  }

  // Normalize alternative key names: tasks, steps, task_list -> subtasks
  const subtasksArray =
    parsed.subtasks ?? parsed.tasks ?? parsed.steps ?? parsed.task_list ?? parsed.decomposition;

  if (!subtasksArray || !Array.isArray(subtasksArray) || subtasksArray.length === 0) {
    return null;
  }

  return {
    subtasks: subtasksArray.map(normalizeSubtask),
    strategy: parsed.strategy || 'adaptive',
    reasoning: parsed.reasoning || '',
  };
}

/**
 * Layer 1: Lenient JSON repair.
 * Fixes common LLM JSON mistakes before parsing:
 * - Trailing commas before ] and }
 * - JS-style comments (// and block comments)
 * - Single-quoted strings -> double-quoted
 * - Unquoted object keys
 */
export function repairJSON(jsonStr: string): string {
  let s = jsonStr;

  // Strip JS-style line comments (// ...) outside strings
  s = s.replace(/("(?:[^"\\]|\\.)*")|\/\/[^\n]*/g, (_match, str) => str ?? '');

  // Strip JS-style block comments outside strings
  s = s.replace(/("(?:[^"\\]|\\.)*")|\/\*[\s\S]*?\*\//g, (_match, str) => str ?? '');

  // Replace single-quoted strings with double-quoted (outside existing double-quoted strings)
  s = s.replace(/("(?:[^"\\]|\\.)*")|'((?:[^'\\]|\\.)*)'/g, (_match, dq, sq) => {
    if (dq) return dq; // Already double-quoted, keep as-is
    const escaped = sq.replace(/(?<!\\)"/g, '\\"');
    return `"${escaped}"`;
  });

  // Fix unquoted object keys: { key: "value" } -> { "key": "value" }
  s = s.replace(/("(?:[^"\\]|\\.)*")|\b([a-zA-Z_][a-zA-Z0-9_]*)\s*:/g, (match, str, key) => {
    if (str) return match; // Inside a string, keep as-is
    return `"${key}":`;
  });

  // Strip trailing commas before ] and }
  s = s.replace(/,\s*([}\]])/g, '$1');

  return s;
}

// =============================================================================
// NATURAL LANGUAGE EXTRACTION
// =============================================================================

/**
 * Layer 2: Extract subtasks from natural language (numbered/bulleted lists).
 * Handles formats like:
 * - "1. Description" / "1) Description"
 * - "- Description" / "* Description"
 * - "Task 1: Description" / "Step 1: Description"
 * - "- [ ] Description" / "- [x] Description" (markdown task lists)
 */
export function extractSubtasksFromNaturalLanguage(response: string): LLMDecomposeResult | null {
  const items: string[] = [];

  // Try markdown task lists first: - [ ] Task / - [x] Task
  const taskListPattern = /^[ \t]*[-*]\s*\[[ x]\]\s+(.+)$/gm;
  let match;
  while ((match = taskListPattern.exec(response)) !== null) {
    const desc = match[1].trim();
    if (desc.length > 5) items.push(desc);
  }
  if (items.length >= 2) return buildSubtasksFromList(items);

  // Try numbered lists: 1. Desc / 1) Desc / 1: Desc
  items.length = 0;
  const numberedPattern = /^[ \t]*\d+[.):\-]\s+(.+)$/gm;
  while ((match = numberedPattern.exec(response)) !== null) {
    const desc = match[1].trim();
    if (desc.length > 5) items.push(desc);
  }
  if (items.length >= 2) return buildSubtasksFromList(items);

  // Try bulleted lists: - Desc / * Desc (but not markdown task lists already tried)
  items.length = 0;
  const bulletPattern = /^[ \t]*[-*]\s+(?!\[[ x]\])(.+)$/gm;
  while ((match = bulletPattern.exec(response)) !== null) {
    const desc = match[1].trim();
    if (desc.length > 5) items.push(desc);
  }
  if (items.length >= 2) return buildSubtasksFromList(items);

  // Try "Task N:" / "Step N:" / "Subtask N:" style headers
  items.length = 0;
  const headerPattern = /^[ \t]*(?:task|step|subtask|phase)\s*\d+[:.]\s*(.+)$/gim;
  while ((match = headerPattern.exec(response)) !== null) {
    const desc = match[1].trim();
    if (desc.length > 5) items.push(desc);
  }
  if (items.length >= 2) return buildSubtasksFromList(items);

  // Try markdown headers: ## Subtask 1 / ### Step: Description
  items.length = 0;
  const mdHeaderPattern = /^#{2,4}\s+(?:(?:subtask|step|task|phase)\s*\d*[:.]*\s*)?(.+)$/gim;
  while ((match = mdHeaderPattern.exec(response)) !== null) {
    const desc = match[1].trim();
    // Skip generic headers like "Summary", "Strategy", "Overview"
    if (
      desc.length > 5 &&
      !/^(summary|strategy|overview|reasoning|conclusion|notes?)$/i.test(desc)
    ) {
      items.push(desc);
    }
  }
  if (items.length >= 2) return buildSubtasksFromList(items);

  return null;
}

/**
 * Build an LLMDecomposeResult from a flat list of description strings.
 * Assigns sequential dependencies and infers task type from keywords.
 */
function buildSubtasksFromList(items: string[]): LLMDecomposeResult {
  const TYPE_KEYWORDS: Record<string, string[]> = {
    research: [
      'research',
      'investigate',
      'explore',
      'analyze',
      'understand',
      'study',
      'review existing',
    ],
    design: ['design', 'plan', 'architect', 'schema', 'structure'],
    test: ['test', 'verify', 'validate', 'assert', 'check'],
    refactor: ['refactor', 'clean up', 'reorganize', 'simplify'],
    document: ['document', 'readme', 'docs', 'comment'],
    integrate: ['integrate', 'wire', 'connect', 'combine', 'merge'],
    deploy: ['deploy', 'release', 'publish', 'ship'],
  };

  return {
    subtasks: items.map((desc, i) => {
      const lower = desc.toLowerCase();
      let type: SubtaskType = 'implement';
      for (const [t, keywords] of Object.entries(TYPE_KEYWORDS)) {
        if (keywords.some((k) => lower.includes(k))) {
          type = t as SubtaskType;
          break;
        }
      }
      return {
        description: desc,
        type,
        complexity: 3,
        dependencies: i > 0 ? [String(i - 1)] : [],
        parallelizable: i === 0 || type === 'research' || type === 'test',
      };
    }),
    strategy: 'sequential',
    reasoning: '(extracted from natural language list)',
  };
}

// =============================================================================
// TRUNCATED JSON RECOVERY
// =============================================================================

/**
 * Layer 3: Last-ditch single mega-task extraction.
 * If there's meaningful text but no structure could be found,
 * wrap the response as a single "implement" subtask so the swarm
 * has something to work with rather than aborting entirely.
 */
function extractMegaTask(response: string): LLMDecomposeResult | null {
  // Strip code blocks, JSON fragments, and whitespace to get prose content
  const prose = response
    .replace(/```[\s\S]*?```/g, '')
    .replace(/\{[\s\S]*?\}/g, '')
    .replace(/\[[\s\S]*?\]/g, '')
    .trim();

  // Only create mega-task if there's substantial text (not just JSON garbage)
  if (prose.length < 20) return null;

  const desc = prose.length > 200 ? prose.slice(0, 200).replace(/\s+\S*$/, '') + '...' : prose;

  return {
    subtasks: [
      {
        description: desc,
        type: 'implement',
        complexity: 5,
        dependencies: [],
        parallelizable: false,
      },
    ],
    strategy: 'adaptive',
    reasoning: '(single mega-task — parser could not extract structured subtasks)',
  };
}

/**
 * Attempt to recover a truncated JSON response by trimming incomplete trailing
 * content and adding missing closing brackets/braces.
 *
 * Works for the common case where the LLM output was cut off mid-JSON-array,
 * e.g.: `{"subtasks": [ {...}, {...}, {"desc` -> trim last incomplete object -> close array & object.
 */
function tryRecoverTruncatedJSON(response: string): string | null {
  // Extract JSON portion (from code block or raw)
  let jsonStr: string | undefined;
  const codeBlockMatch = response.match(/```(?:json)?\s*\n?([\s\S]*)/);
  if (codeBlockMatch) {
    // No closing ``` required — that's the truncation
    jsonStr = codeBlockMatch[1].replace(/```\s*$/, '').trim();
  }
  if (!jsonStr) {
    const jsonMatch = response.match(/\{[\s\S]*/);
    if (jsonMatch) jsonStr = jsonMatch[0].trim();
  }
  if (!jsonStr) return null;

  // Find the last complete JSON object in the subtasks array.
  // Strategy: find last `}` that closes a complete array element, trim there, close brackets.
  // We search backwards for `},` or `}\n` patterns that likely end a complete subtask object.
  let lastGoodPos = -1;
  let braceDepth = 0;
  let bracketDepth = 0;
  let inString = false;
  let escape = false;

  for (let i = 0; i < jsonStr.length; i++) {
    const ch = jsonStr[i];
    if (escape) {
      escape = false;
      continue;
    }
    if (ch === '\\' && inString) {
      escape = true;
      continue;
    }
    if (ch === '"') {
      inString = !inString;
      continue;
    }
    if (inString) continue;

    if (ch === '{') braceDepth++;
    else if (ch === '}') {
      braceDepth--;
      // When we close an object at brace depth 1 (inside the top-level object),
      // this is likely a complete subtask object inside the array
      if (braceDepth === 1 && bracketDepth === 1) {
        lastGoodPos = i;
      }
    } else if (ch === '[') bracketDepth++;
    else if (ch === ']') bracketDepth--;
  }

  if (lastGoodPos === -1) return null;

  // Trim to last complete subtask object, then close the JSON structure
  let trimmed = jsonStr.slice(0, lastGoodPos + 1);
  // Remove trailing comma if present
  trimmed = trimmed.replace(/,\s*$/, '');
  // Close open brackets: we need to close the subtasks array and the root object
  // Count what's still open
  let openBraces = 0;
  let openBrackets = 0;
  inString = false;
  escape = false;
  for (let i = 0; i < trimmed.length; i++) {
    const ch = trimmed[i];
    if (escape) {
      escape = false;
      continue;
    }
    if (ch === '\\' && inString) {
      escape = true;
      continue;
    }
    if (ch === '"') {
      inString = !inString;
      continue;
    }
    if (inString) continue;
    if (ch === '{') openBraces++;
    else if (ch === '}') openBraces--;
    else if (ch === '[') openBrackets++;
    else if (ch === ']') openBrackets--;
  }

  // Close remaining open structures
  for (let i = 0; i < openBrackets; i++) trimmed += ']';
  for (let i = 0; i < openBraces; i++) trimmed += '}';

  return trimmed;
}

// =============================================================================
// MAIN PARSE FUNCTION
// =============================================================================

/**
 * Parse LLM response into decomposition result.
 *
 * Uses progressive fallback layers to handle messy LLM output:
 * 1. Standard JSON extraction (code blocks, raw JSON)
 * 2. Lenient JSON repair (trailing commas, comments, single quotes, unquoted keys)
 * 3. Truncated JSON recovery (missing closing brackets)
 * 4. Natural language extraction (numbered/bulleted lists, markdown task lists)
 * 5. Single mega-task fallback (wrap prose as one subtask)
 */
export function parseDecompositionResponse(response: string): LLMDecomposeResult {
  if (!response || response.trim().length === 0) {
    return {
      subtasks: [],
      strategy: 'adaptive',
      reasoning: '',
      parseError: 'Empty response from LLM',
    };
  }

  // -- Step 1: Extract JSON string (code block or raw) --
  let jsonStr: string | undefined;
  const codeBlockMatch = response.match(/```(?:json)?\s*\n?([\s\S]*?)```/);
  if (codeBlockMatch) {
    jsonStr = codeBlockMatch[1].trim();
  }
  if (!jsonStr) {
    // If the response starts with `[`, try array regex first to avoid
    // \{[\s\S]*\} greedily matching across multiple objects in the array
    const trimmed = response.trim();
    const jsonMatch = trimmed.startsWith('[')
      ? response.match(/\[[\s\S]*\]/) || response.match(/\{[\s\S]*\}/)
      : response.match(/\{[\s\S]*\}/) || response.match(/\[[\s\S]*\]/);
    if (jsonMatch) jsonStr = jsonMatch[0];
  }

  // -- Step 2: Try strict JSON parse --
  if (jsonStr) {
    try {
      const parsed = JSON.parse(jsonStr);
      const result = extractSubtasksFromParsed(parsed);
      if (result) return result;
    } catch {
      // Strict parse failed — continue to lenient repair
    }

    // -- Step 3: Lenient JSON repair + parse --
    try {
      const repaired = repairJSON(jsonStr);
      const parsed = JSON.parse(repaired);
      const result = extractSubtasksFromParsed(parsed);
      if (result) {
        result.reasoning = result.reasoning
          ? result.reasoning + ' (repaired JSON)'
          : '(repaired JSON)';
        return result;
      }
    } catch {
      // Repaired parse also failed — continue to truncation recovery
    }
  }

  // -- Step 4: Truncated JSON recovery --
  const recovered = tryRecoverTruncatedJSON(response);
  if (recovered) {
    try {
      const parsed = JSON.parse(recovered);
      const result = extractSubtasksFromParsed(parsed);
      if (result) {
        result.reasoning = result.reasoning
          ? result.reasoning + ' (recovered from truncated response)'
          : '(recovered from truncated response)';
        return result;
      }
    } catch {
      // Truncation recovery also failed — try repaired version
      try {
        const repairedRecovered = repairJSON(recovered);
        const parsed = JSON.parse(repairedRecovered);
        const result = extractSubtasksFromParsed(parsed);
        if (result) {
          result.reasoning = '(recovered from truncated + repaired JSON)';
          return result;
        }
      } catch {
        // All JSON approaches exhausted
      }
    }
  }

  // -- Step 5: Natural language extraction --
  const nlResult = extractSubtasksFromNaturalLanguage(response);
  if (nlResult) return nlResult;

  // -- Step 6: Single mega-task fallback --
  const megaResult = extractMegaTask(response);
  if (megaResult) return megaResult;

  // -- Truly nothing worked --
  return {
    subtasks: [],
    strategy: 'adaptive',
    reasoning: '',
    parseError: `All parse strategies failed. First 200 chars: ${response.slice(0, 200)}`,
  };
}
