/**
 * ToolCall Component
 *
 * Displays tool execution status with expandable details.
 */

import React, { useState } from 'react';
import { Box, Text, useInput } from 'ink';
import Spinner from 'ink-spinner';
import type { ToolCallDisplay } from '../types.js';
import type { Theme } from '../theme/index.js';

export interface ToolCallProps {
  theme: Theme;
  toolCall: ToolCallDisplay;
  expanded?: boolean;
  onToggle?: () => void;
  showDuration?: boolean;
  showArgs?: boolean;
}

export interface ToolCallListProps {
  theme: Theme;
  toolCalls: Map<string, ToolCallDisplay> | ToolCallDisplay[];
  maxVisible?: number;
  title?: string;
  /** When true, all tool calls are expanded globally (overrides individual expansion) */
  globalExpanded?: boolean;
}

// Status configuration with emoji icons for better visual distinction
const statusConfig: Record<string, { icon: string; label: string }> = {
  pending: { icon: '⏳', label: 'pending' },
  running: { icon: '🔄', label: 'running' },
  success: { icon: '✅', label: 'done' },
  error: { icon: '❌', label: 'error' },
};

/**
 * Format duration in human-readable format.
 */
function formatDuration(ms: number | undefined): string {
  if (ms === undefined) return '';
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${ms}ms`;
}

/**
 * Truncate and format tool arguments for display.
 */
function formatArgs(args: Record<string, unknown>, maxLength = 60): string {
  const str = JSON.stringify(args);
  if (str.length <= maxLength) return str;
  return str.slice(0, maxLength - 3) + '...';
}

/**
 * Single tool call item component.
 */
export function ToolCall({
  theme,
  toolCall,
  expanded = false,
  onToggle,
  showDuration = true,
  showArgs = false,
}: ToolCallProps) {
  const config = statusConfig[toolCall.status] || statusConfig.pending;

  // Get status color
  const getStatusColor = (status: string): string => {
    switch (status) {
      case 'pending': return theme.colors.textMuted;
      case 'running': return theme.colors.info;
      case 'success': return theme.colors.success;
      case 'error': return theme.colors.error;
      default: return theme.colors.text;
    }
  };

  const statusColor = getStatusColor(toolCall.status);

  return (
    <Box flexDirection="column" marginBottom={1}>
      {/* Main row */}
      <Box gap={2}>
        {/* Status indicator */}
        <Text color={statusColor}>
          {toolCall.status === 'running' ? (
            <Spinner type="dots" />
          ) : (
            config.icon
          )}
        </Text>

        {/* Tool name */}
        <Text color={theme.colors.toolMessage} bold>
          {toolCall.name}
        </Text>

        {/* Duration */}
        {showDuration && toolCall.duration !== undefined && (
          <Text color={theme.colors.textMuted}>
            ({formatDuration(toolCall.duration)})
          </Text>
        )}

        {/* Expand indicator */}
        {onToggle && (
          <Text color={theme.colors.textMuted}>
            {expanded ? '[-]' : '[+]'}
          </Text>
        )}
      </Box>

      {/* Arguments (when expanded or showArgs is true) */}
      {(expanded || showArgs) && Object.keys(toolCall.args).length > 0 && (
        <Box marginLeft={4} marginTop={1} paddingY={1}>
          <Text color={theme.colors.textMuted} dimColor>
            {expanded
              ? JSON.stringify(toolCall.args, null, 2)
              : formatArgs(toolCall.args)
            }
          </Text>
        </Box>
      )}

      {/* Result or Error (when expanded) */}
      {expanded && toolCall.status === 'success' && toolCall.result !== undefined && (
        <Box marginLeft={4} marginTop={2} marginBottom={1} flexDirection="column">
          <Text color={theme.colors.success} bold>Result:</Text>
          <Box marginLeft={2} marginTop={1}>
            <Text color={theme.colors.text} wrap="wrap">
              {typeof toolCall.result === 'string'
                ? toolCall.result.slice(0, 500) + (toolCall.result.length > 500 ? '...' : '')
                : JSON.stringify(toolCall.result, null, 2).slice(0, 500)
              }
            </Text>
          </Box>
        </Box>
      )}

      {expanded && toolCall.status === 'error' && toolCall.error && (
        <Box marginLeft={4} marginTop={2} marginBottom={1} flexDirection="column">
          <Text color={theme.colors.error} bold>Error:</Text>
          <Box marginLeft={2} marginTop={1}>
            <Text color={theme.colors.error}>{toolCall.error}</Text>
          </Box>
        </Box>
      )}
    </Box>
  );
}

/**
 * List of tool calls with optional grouping.
 */
export function ToolCallList({
  theme,
  toolCalls,
  maxVisible = 5,
  title = 'Tools',
  globalExpanded,
}: ToolCallListProps) {
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  // Convert Map to array if needed
  const callsArray = toolCalls instanceof Map
    ? Array.from(toolCalls.values())
    : toolCalls;

  if (callsArray.length === 0) return null;

  // Get visible calls (most recent)
  const visibleCalls = callsArray.slice(-maxVisible);
  const hiddenCount = callsArray.length - visibleCalls.length;

  // Count by status
  const counts = {
    running: callsArray.filter(c => c.status === 'running').length,
    success: callsArray.filter(c => c.status === 'success').length,
    error: callsArray.filter(c => c.status === 'error').length,
    pending: callsArray.filter(c => c.status === 'pending').length,
  };

  const toggleExpanded = (id: string) => {
    setExpandedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  return (
    <Box
      flexDirection="column"
      borderStyle="round"
      borderColor={theme.colors.border}
      paddingX={2}
      paddingY={1}
      marginTop={1}
      marginBottom={1}
    >
      {/* Header */}
      <Box justifyContent="space-between" marginBottom={2}>
        <Text bold color={theme.colors.toolMessage}>{title}</Text>
        <Box gap={1}>
          {counts.running > 0 && (
            <Text color={theme.colors.info}>{counts.running} running</Text>
          )}
          {counts.success > 0 && (
            <Text color={theme.colors.success}>{counts.success} done</Text>
          )}
          {counts.error > 0 && (
            <Text color={theme.colors.error}>{counts.error} failed</Text>
          )}
        </Box>
      </Box>

      {/* Hidden count */}
      {hiddenCount > 0 && (
        <Box marginBottom={1}>
          <Text color={theme.colors.textMuted}>
            ... {hiddenCount} more tools above
          </Text>
        </Box>
      )}

      {/* Tool calls */}
      {visibleCalls.map((tc) => {
        // globalExpanded overrides individual expansion state
        const isExpanded = globalExpanded !== undefined ? globalExpanded : expandedIds.has(tc.id);
        return (
          <Box key={tc.id} marginBottom={2}>
            <ToolCall
              theme={theme}
              toolCall={tc}
              expanded={isExpanded}
              onToggle={globalExpanded === undefined ? () => toggleExpanded(tc.id) : undefined}
              showDuration
              showArgs={!isExpanded}
            />
          </Box>
        );
      })}
    </Box>
  );
}

export default ToolCall;
