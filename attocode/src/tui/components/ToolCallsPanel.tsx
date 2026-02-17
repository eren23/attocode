/**
 * ToolCallsPanel Component
 *
 * Memoized panel showing recent tool calls during agent execution.
 * Extracted from TUIApp to prevent re-renders when other TUIApp state changes.
 */

import { memo } from 'react';
import { Box, Text } from 'ink';
import { ToolCallItem, type ToolCallDisplayItem } from './ToolCallItem.js';
import type { ThemeColors } from '../types.js';

export interface ToolCallsPanelProps {
  toolCalls: ToolCallDisplayItem[];
  expanded: boolean;
  colors: ThemeColors;
}

export const ToolCallsPanel = memo(
  function ToolCallsPanel({ toolCalls, expanded, colors }: ToolCallsPanelProps) {
    if (toolCalls.length === 0) return null;

    return (
      <Box flexDirection="column" marginBottom={1}>
        <Text color="#DDA0DD" bold>{`Tools ${expanded ? '[-]' : '[+]'}`}</Text>
        {toolCalls.slice(-5).map((tc) => (
          <ToolCallItem
            key={`${tc.id}-${tc.status}`}
            tc={tc}
            expanded={expanded}
            colors={colors}
          />
        ))}
      </Box>
    );
  },
  (prevProps, nextProps) => {
    // Only re-render if tool calls changed or expanded toggled
    if (prevProps.expanded !== nextProps.expanded) return false;
    if (prevProps.toolCalls.length !== nextProps.toolCalls.length) return false;
    // Check if the last tool call changed (most common case)
    const prevLast = prevProps.toolCalls[prevProps.toolCalls.length - 1];
    const nextLast = nextProps.toolCalls[nextProps.toolCalls.length - 1];
    if (prevLast?.id !== nextLast?.id || prevLast?.status !== nextLast?.status) return false;
    return true;
  },
);
