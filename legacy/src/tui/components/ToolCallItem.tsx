/**
 * ToolCallItem Component
 *
 * Memoized tool call display that shows tool execution status.
 * Supports expanded and collapsed views with DiffView integration.
 */

import { memo } from 'react';
import { Box, Text } from 'ink';
import { DiffView } from './DiffView.js';
import type { ThemeColors } from '../types.js';

/**
 * Tool call display data structure.
 */
export interface ToolCallDisplayItem {
  id: string;
  name: string;
  args: Record<string, unknown>;
  status: 'pending' | 'running' | 'success' | 'error';
  result?: unknown;
  error?: string;
  duration?: number;
  startTime?: Date;
}

export interface ToolCallItemProps {
  tc: ToolCallDisplayItem;
  expanded: boolean;
  colors: ThemeColors;
}

/**
 * Extract the base tool name, stripping subagent prefixes.
 * e.g., "researcher:edit_file" → "edit_file"
 */
function getBaseToolName(name: string): string {
  return name.includes(':') ? name.split(':').pop()! : name;
}

/**
 * Check if a tool name is a file operation (accounting for subagent prefixes).
 */
function isFileOperation(name: string): boolean {
  const base = getBaseToolName(name);
  return base === 'edit_file' || base === 'write_file';
}

/**
 * Extract displayable text from a tool result.
 * Handles ToolResult objects that have an `output` field to avoid [object Object].
 */
function getResultText(result: unknown): string {
  if (typeof result === 'string') return result;
  if (typeof result === 'object' && result !== null && 'output' in result) {
    return String((result as { output: unknown }).output);
  }
  return String(result);
}

/**
 * Helper to format tool args concisely for collapsed view.
 */
function formatToolArgsCompact(args: Record<string, unknown>): string {
  const entries = Object.entries(args);
  if (entries.length === 0) return '';
  if (entries.length === 1) {
    const [key, val] = entries[0];
    const valStr = typeof val === 'string' ? val : JSON.stringify(val);
    return valStr.length > 50 ? `${key}: ${valStr.slice(0, 47)}...` : `${key}: ${valStr}`;
  }
  return `{${entries.length} args}`;
}

/**
 * Format tool args for expanded view with proper indentation.
 * Shows all arguments without truncation.
 */
function formatToolArgsExpanded(args: Record<string, unknown>): string[] {
  const entries = Object.entries(args);
  if (entries.length === 0) return [];

  return entries.map(([key, val]) => {
    let valStr: string;
    if (typeof val === 'string') {
      // For strings, show with quotes, handle multiline
      if (val.includes('\n')) {
        const lines = val.split('\n');
        if (lines.length > 3) {
          valStr = `"${lines.slice(0, 3).join('\\n')}..." (${lines.length} lines)`;
        } else {
          valStr = `"${val.replace(/\n/g, '\\n')}"`;
        }
      } else if (val.length > 100) {
        valStr = `"${val.slice(0, 97)}..."`;
      } else {
        valStr = `"${val}"`;
      }
    } else if (typeof val === 'object' && val !== null) {
      const json = JSON.stringify(val, null, 2);
      if (json.length > 200) {
        valStr = JSON.stringify(val).slice(0, 197) + '...';
      } else {
        valStr = json;
      }
    } else {
      valStr = String(val);
    }
    return `${key}: ${valStr}`;
  });
}

/**
 * Check if a tool result contains diff metadata.
 */
function getDiffString(tc: ToolCallDisplayItem): string | null {
  if (tc.status !== 'success' || !isFileOperation(tc.name)) return null;
  if (
    typeof tc.result === 'object' &&
    tc.result !== null &&
    'metadata' in tc.result &&
    typeof (tc.result as { metadata?: { diff?: string } }).metadata?.diff === 'string'
  ) {
    return (tc.result as { metadata: { diff: string } }).metadata.diff;
  }
  return null;
}

/**
 * Memoized tool call item - displays tool execution status.
 * Supports expanded view with full args, diff rendering, and result preview.
 */
export const ToolCallItem = memo(function ToolCallItem({
  tc,
  expanded,
  colors,
}: ToolCallItemProps) {
  const icon =
    tc.status === 'success'
      ? '[OK]'
      : tc.status === 'error'
        ? '[X]'
        : tc.status === 'running'
          ? '[~]'
          : '[ ]';
  const statusColor =
    tc.status === 'success'
      ? '#98FB98'
      : tc.status === 'error'
        ? '#FF6B6B'
        : tc.status === 'running'
          ? '#87CEEB'
          : colors.textMuted;
  const diffString = getDiffString(tc);

  if (expanded) {
    const expandedArgs = formatToolArgsExpanded(tc.args);

    return (
      <Box marginLeft={2} flexDirection="column">
        <Box gap={1}>
          <Text color={statusColor}>{icon}</Text>
          <Text color="#DDA0DD" bold>
            {tc.name}
          </Text>
          {tc.duration ? (
            <Text color={colors.textMuted} dimColor>
              ({tc.duration}ms)
            </Text>
          ) : null}
        </Box>
        {/* Show each arg on its own line for readability */}
        {expandedArgs.map((argLine, i) => (
          <Box key={i} marginLeft={3}>
            <Text color="#87CEEB" dimColor>
              {argLine}
            </Text>
          </Box>
        ))}
        {tc.status === 'success' && tc.result !== undefined && tc.result !== null ? (
          <Box marginLeft={3} flexDirection="column">
            {/* Show diff if available for file operations */}
            {diffString ? (
              <DiffView
                diff={diffString}
                expanded={true}
                maxLines={15}
                showWordDiff={true}
                showLineNumbers={true}
              />
            ) : (
              <Text color="#98FB98" dimColor>
                {(() => {
                  const text = getResultText(tc.result);
                  return `-> ${text.slice(0, 150)}${text.length > 150 ? '...' : ''}`;
                })()}
              </Text>
            )}
          </Box>
        ) : null}
        {tc.status === 'error' && tc.error && (
          <Box marginLeft={3}>
            <Text color="#FF6B6B">{`x ${tc.error}`}</Text>
          </Box>
        )}
      </Box>
    );
  }

  // Collapsed view (default) - compact single line
  const argsStr = formatToolArgsCompact(tc.args);

  return (
    <Box marginLeft={2} gap={1}>
      <Text color={statusColor}>{icon}</Text>
      <Text color="#DDA0DD" bold>
        {tc.name}
      </Text>
      {argsStr ? (
        <Text color={colors.textMuted} dimColor>
          {argsStr}
        </Text>
      ) : null}
      {/* Show diff summary in collapsed view */}
      {diffString && <DiffView diff={diffString} expanded={false} />}
      {tc.duration ? (
        <Text color={colors.textMuted} dimColor>
          ({tc.duration}ms)
        </Text>
      ) : null}
    </Box>
  );
});

export default ToolCallItem;
