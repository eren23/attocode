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
 * Helper to format tool args concisely.
 */
function formatToolArgs(args: Record<string, unknown>): string {
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
 * Memoized tool call item - displays tool execution status.
 * Supports expanded view with args and result preview.
 */
export const ToolCallItem = memo(function ToolCallItem({ tc, expanded, colors }: ToolCallItemProps) {
  const icon = tc.status === 'success' ? '+' : tc.status === 'error' ? 'x' : tc.status === 'running' ? '~' : 'o';
  const statusColor = tc.status === 'success' ? '#98FB98' : tc.status === 'error' ? '#FF6B6B' : tc.status === 'running' ? '#87CEEB' : colors.textMuted;

  const argsStr = formatToolArgs(tc.args);

  // Expanded view shows more details
  if (expanded) {
    return React.createElement(Box, { marginLeft: 2, flexDirection: 'column' },
      React.createElement(Box, { gap: 1 },
        React.createElement(Text, { color: statusColor }, icon),
        React.createElement(Text, { color: '#DDA0DD', bold: true }, tc.name),
        tc.duration ? React.createElement(Text, { color: colors.textMuted, dimColor: true }, `(${tc.duration}ms)`) : null
      ),
      // Show args in expanded mode
      Object.keys(tc.args).length > 0 ? React.createElement(Box, { marginLeft: 3 },
        React.createElement(Text, { color: colors.textMuted, dimColor: true },
          JSON.stringify(tc.args, null, 0).slice(0, 100) + (JSON.stringify(tc.args).length > 100 ? '...' : '')
        )
      ) : null,
      // Show result preview in expanded mode
      (tc.status === 'success' && tc.result) ? React.createElement(Box, { marginLeft: 3 },
        React.createElement(Text, { color: '#98FB98', dimColor: true },
          `-> ${String(tc.result).slice(0, 80)}${String(tc.result).length > 80 ? '...' : ''}`
        )
      ) : null,
      // Show error in expanded mode
      (tc.status === 'error' && tc.error) ? React.createElement(Box, { marginLeft: 3 },
        React.createElement(Text, { color: '#FF6B6B' }, `x ${tc.error}`)
      ) : null
    );
  }

  // Collapsed view (default)
  return React.createElement(Box, { marginLeft: 2, gap: 1 },
    React.createElement(Text, { color: statusColor }, icon),
    React.createElement(Text, { color: '#DDA0DD', bold: true }, tc.name),
    argsStr ? React.createElement(Text, { color: colors.textMuted, dimColor: true }, argsStr) : null,
    tc.duration ? React.createElement(Text, { color: colors.textMuted, dimColor: true }, `(${tc.duration}ms)`) : null
  );
});

export default ToolCallItem;
