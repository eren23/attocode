/**
 * ToolCallItem Component
 *
 * Memoized tool call display that shows tool execution status.
 * Supports expanded and collapsed views.
 */

import React, { memo } from 'react';
import { Box, Text } from 'ink';
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
 * Memoized tool call item - displays tool execution status.
 * Supports expanded view with full args and result preview.
 */
export const ToolCallItem = memo(function ToolCallItem({ tc, expanded, colors }: ToolCallItemProps) {
  const icon = tc.status === 'success' ? '+' : tc.status === 'error' ? 'x' : tc.status === 'running' ? '~' : 'o';
  const statusColor = tc.status === 'success' ? '#98FB98' : tc.status === 'error' ? '#FF6B6B' : tc.status === 'running' ? '#87CEEB' : colors.textMuted;

  // Expanded view shows full details
  if (expanded) {
    const expandedArgs = formatToolArgsExpanded(tc.args);

    return React.createElement(Box, { marginLeft: 2, flexDirection: 'column' },
      // Header line: icon, name, duration
      React.createElement(Box, { gap: 1 },
        React.createElement(Text, { color: statusColor }, icon),
        React.createElement(Text, { color: '#DDA0DD', bold: true }, tc.name),
        tc.duration ? React.createElement(Text, { color: colors.textMuted, dimColor: true }, `(${tc.duration}ms)`) : null
      ),
      // Show each arg on its own line for readability
      ...expandedArgs.map((argLine, i) =>
        React.createElement(Box, { key: i, marginLeft: 3 },
          React.createElement(Text, { color: '#87CEEB', dimColor: true }, argLine)
        )
      ),
      // Show result preview in expanded mode
      (tc.status === 'success' && tc.result) ? React.createElement(Box, { marginLeft: 3 },
        React.createElement(Text, { color: '#98FB98', dimColor: true },
          `-> ${String(tc.result).slice(0, 150)}${String(tc.result).length > 150 ? '...' : ''}`
        )
      ) : null,
      // Show error in expanded mode
      (tc.status === 'error' && tc.error) ? React.createElement(Box, { marginLeft: 3 },
        React.createElement(Text, { color: '#FF6B6B' }, `x ${tc.error}`)
      ) : null
    );
  }

  // Collapsed view (default) - compact single line
  const argsStr = formatToolArgsCompact(tc.args);
  return React.createElement(Box, { marginLeft: 2, gap: 1 },
    React.createElement(Text, { color: statusColor }, icon),
    React.createElement(Text, { color: '#DDA0DD', bold: true }, tc.name),
    argsStr ? React.createElement(Text, { color: colors.textMuted, dimColor: true }, argsStr) : null,
    tc.duration ? React.createElement(Text, { color: colors.textMuted, dimColor: true }, `(${tc.duration}ms)`) : null
  );
});

export default ToolCallItem;
