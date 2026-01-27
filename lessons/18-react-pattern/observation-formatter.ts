/**
 * Lesson 18: Observation Formatter
 *
 * Formats tool results into observations for the ReAct loop.
 * Handles truncation, summarization, and structured output.
 */

import type {
  ObservationFormatOptions,
  FormattedObservation,
} from './types.js';
import type { ToolResult } from '../03-tool-system/types.js';

// =============================================================================
// DEFAULT OPTIONS
// =============================================================================

const DEFAULT_OPTIONS: ObservationFormatOptions = {
  maxLength: 1000,
  truncation: 'end',
  asCodeBlock: false,
  includeMetadata: false,
};

// =============================================================================
// MAIN FORMATTER
// =============================================================================

/**
 * Format a tool result into an observation string.
 */
export function formatObservation(
  result: ToolResult | string,
  options: Partial<ObservationFormatOptions> = {}
): FormattedObservation {
  const opts = { ...DEFAULT_OPTIONS, ...options };

  // Convert to string
  let content: string;
  if (typeof result === 'string') {
    content = result;
  } else {
    content = formatToolResult(result, opts.includeMetadata);
  }

  const originalLength = content.length;
  let truncated = false;

  // Apply truncation if needed
  if (content.length > opts.maxLength) {
    content = truncateContent(content, opts.maxLength, opts.truncation);
    truncated = true;
  }

  // Wrap in code block if requested
  if (opts.asCodeBlock) {
    content = '```\n' + content + '\n```';
  }

  return {
    content,
    truncated,
    originalLength,
  };
}

// =============================================================================
// TOOL RESULT FORMATTING
// =============================================================================

/**
 * Format a ToolResult into a string.
 */
function formatToolResult(result: ToolResult, includeMetadata: boolean): string {
  const parts: string[] = [];

  // Main output
  if (result.output) {
    parts.push(result.output);
  }

  // Success/failure indicator
  if (!result.success) {
    parts.unshift('[FAILED] ');
  }

  // Metadata
  if (includeMetadata && result.metadata) {
    const metaStr = Object.entries(result.metadata)
      .map(([k, v]) => `${k}: ${JSON.stringify(v)}`)
      .join(', ');
    parts.push(`\n[Metadata: ${metaStr}]`);
  }

  return parts.join('');
}

// =============================================================================
// TRUNCATION
// =============================================================================

/**
 * Truncate content to max length.
 */
function truncateContent(
  content: string,
  maxLength: number,
  strategy: 'end' | 'middle' | 'summarize'
): string {
  switch (strategy) {
    case 'end':
      return truncateEnd(content, maxLength);

    case 'middle':
      return truncateMiddle(content, maxLength);

    case 'summarize':
      return summarize(content, maxLength);

    default:
      return truncateEnd(content, maxLength);
  }
}

/**
 * Truncate from the end.
 */
function truncateEnd(content: string, maxLength: number): string {
  if (content.length <= maxLength) return content;

  const truncated = content.slice(0, maxLength - 30);

  // Try to break at a natural point
  const lastNewline = truncated.lastIndexOf('\n');
  const lastSpace = truncated.lastIndexOf(' ');
  const breakPoint = Math.max(lastNewline, lastSpace, maxLength - 100);

  return truncated.slice(0, breakPoint) + '\n... [truncated]';
}

/**
 * Truncate from the middle, keeping start and end.
 */
function truncateMiddle(content: string, maxLength: number): string {
  if (content.length <= maxLength) return content;

  const halfLength = Math.floor((maxLength - 30) / 2);
  const start = content.slice(0, halfLength);
  const end = content.slice(-halfLength);

  return start + '\n... [middle truncated] ...\n' + end;
}

/**
 * Summarize long content (simple implementation).
 */
function summarize(content: string, maxLength: number): string {
  if (content.length <= maxLength) return content;

  // Extract key information
  const lines = content.split('\n');

  // Keep first few and last few lines
  const keepLines = Math.floor((maxLength - 50) / 80); // Assume ~80 chars per line
  const halfKeep = Math.floor(keepLines / 2);

  if (lines.length <= keepLines) {
    return truncateEnd(content, maxLength);
  }

  const firstLines = lines.slice(0, halfKeep);
  const lastLines = lines.slice(-halfKeep);
  const summary = [
    ...firstLines,
    `... [${lines.length - keepLines} lines omitted] ...`,
    ...lastLines,
  ].join('\n');

  // Final truncation if still too long
  if (summary.length > maxLength) {
    return truncateEnd(summary, maxLength);
  }

  return summary;
}

// =============================================================================
// SPECIALIZED FORMATTERS
// =============================================================================

/**
 * Format file content observation.
 */
export function formatFileContent(
  path: string,
  content: string,
  options: Partial<ObservationFormatOptions> = {}
): FormattedObservation {
  const header = `File: ${path}\n${'─'.repeat(40)}\n`;
  const fullContent = header + content;

  return formatObservation(fullContent, {
    ...options,
    asCodeBlock: true,
  });
}

/**
 * Format command output observation.
 */
export function formatCommandOutput(
  command: string,
  stdout: string,
  stderr: string,
  exitCode: number,
  options: Partial<ObservationFormatOptions> = {}
): FormattedObservation {
  const parts: string[] = [];

  parts.push(`$ ${command}`);
  parts.push(`Exit code: ${exitCode}`);

  if (stdout) {
    parts.push('\nSTDOUT:\n' + stdout);
  }

  if (stderr) {
    parts.push('\nSTDERR:\n' + stderr);
  }

  return formatObservation(parts.join('\n'), options);
}

/**
 * Format search results observation.
 */
export function formatSearchResults(
  query: string,
  results: Array<{ file: string; line: number; content: string }>,
  options: Partial<ObservationFormatOptions> = {}
): FormattedObservation {
  const parts: string[] = [`Search: "${query}"`, `Found ${results.length} results:`, ''];

  for (const result of results) {
    parts.push(`${result.file}:${result.line}: ${result.content.trim()}`);
  }

  return formatObservation(parts.join('\n'), options);
}

/**
 * Format list observation.
 */
export function formatList(
  items: string[],
  options: Partial<ObservationFormatOptions> = {}
): FormattedObservation {
  const content = items.map((item, i) => `${i + 1}. ${item}`).join('\n');
  return formatObservation(content, options);
}

/**
 * Format error observation.
 */
export function formatError(
  error: Error | string,
  context?: string,
  options: Partial<ObservationFormatOptions> = {}
): FormattedObservation {
  const errorMsg = error instanceof Error ? error.message : error;
  const parts: string[] = ['[ERROR]', errorMsg];

  if (context) {
    parts.push(`Context: ${context}`);
  }

  if (error instanceof Error && error.stack) {
    parts.push('\nStack trace:\n' + error.stack.split('\n').slice(1, 4).join('\n'));
  }

  return formatObservation(parts.join('\n'), options);
}

// =============================================================================
// JSON FORMATTING
// =============================================================================

/**
 * Format JSON data as observation.
 */
export function formatJson(
  data: unknown,
  options: Partial<ObservationFormatOptions> = {}
): FormattedObservation {
  let content: string;

  try {
    content = JSON.stringify(data, null, 2);
  } catch {
    content = String(data);
  }

  return formatObservation(content, {
    ...options,
    asCodeBlock: true,
  });
}

/**
 * Format JSON with key highlighting.
 */
export function formatJsonWithHighlights(
  data: Record<string, unknown>,
  highlightKeys: string[],
  options: Partial<ObservationFormatOptions> = {}
): FormattedObservation {
  const highlighted: Record<string, unknown> = {};
  const rest: Record<string, unknown> = {};

  for (const [key, value] of Object.entries(data)) {
    if (highlightKeys.includes(key)) {
      highlighted[key] = value;
    } else {
      rest[key] = value;
    }
  }

  const parts: string[] = [];

  if (Object.keys(highlighted).length > 0) {
    parts.push('Key information:');
    parts.push(JSON.stringify(highlighted, null, 2));
  }

  if (Object.keys(rest).length > 0) {
    parts.push('\nOther data:');
    parts.push(JSON.stringify(rest, null, 2));
  }

  return formatObservation(parts.join('\n'), options);
}

// =============================================================================
// EXPORTS
// =============================================================================

export { DEFAULT_OPTIONS };
