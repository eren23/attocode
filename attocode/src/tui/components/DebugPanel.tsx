/**
 * Debug Panel Component
 *
 * Displays real-time debug logging in a collapsible panel.
 * Toggle with Alt+D to show/hide debug output.
 *
 * Features:
 * - Ring buffer for last N debug messages
 * - Auto-scroll to latest
 * - Color-coded log levels
 * - Timestamp display
 */

import { memo, useState, useRef } from 'react';
import { Box, Text } from 'ink';
import type { ThemeColors } from '../types.js';

// =============================================================================
// TYPES
// =============================================================================

export interface DebugEntry {
  id: string;
  timestamp: Date;
  level: 'debug' | 'info' | 'warn' | 'error';
  message: string;
  data?: Record<string, unknown>;
}

export interface DebugPanelProps {
  entries: DebugEntry[];
  expanded: boolean;
  colors: ThemeColors;
  maxVisible?: number;
}

// =============================================================================
// HELPERS
// =============================================================================

function getLevelColor(level: DebugEntry['level'], colors: ThemeColors): string {
  switch (level) {
    case 'error': return colors.error;
    case 'warn': return colors.warning;
    case 'info': return colors.info;
    case 'debug': return colors.textMuted;
    default: return colors.text;
  }
}

function getLevelIcon(level: DebugEntry['level']): string {
  switch (level) {
    case 'error': return '[X]';
    case 'warn': return '[!]';
    case 'info': return '[i]';
    case 'debug': return '[.]';
    default: return '[-]';
  }
}

function formatTimestamp(date: Date): string {
  return date.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

function formatData(data: Record<string, unknown>): string {
  try {
    const str = JSON.stringify(data);
    return str.length > 100 ? str.slice(0, 97) + '...' : str;
  } catch {
    return '[object]';
  }
}

// =============================================================================
// COMPONENT
// =============================================================================

export const DebugPanel = memo(function DebugPanel({
  entries,
  expanded,
  colors,
  maxVisible = 10,
}: DebugPanelProps) {
  // Don't render if collapsed or no entries
  if (!expanded) {
    return null;
  }

  if (entries.length === 0) {
    return (
      <Box
        flexDirection="column"
        marginBottom={1}
        borderStyle="single"
        borderColor={colors.border}
        paddingX={1}
      >
        <Text color={colors.accent} bold>[v] Debug Panel (Alt+D to toggle)</Text>
        <Text color={colors.textMuted} dimColor>  No debug messages yet</Text>
      </Box>
    );
  }

  // Show only the most recent entries
  const visibleEntries = entries.slice(-maxVisible);

  return (
    <Box
      flexDirection="column"
      marginBottom={1}
      borderStyle="single"
      borderColor={colors.border}
      paddingX={1}
    >
      <Box justifyContent="space-between">
        <Text color={colors.accent} bold>[v] Debug Panel</Text>
        <Text color={colors.textMuted} dimColor>
          {entries.length > maxVisible ? `${entries.length - maxVisible}+ older | ` : ''}
          {entries.length} total
        </Text>
      </Box>
      <Box flexDirection="column" marginTop={1}>
        {visibleEntries.map(entry => (
          <Box key={entry.id} gap={1}>
            <Text color={colors.textMuted} dimColor>
              {formatTimestamp(entry.timestamp)}
            </Text>
            <Text color={getLevelColor(entry.level, colors)}>
              {getLevelIcon(entry.level)}
            </Text>
            <Text color={getLevelColor(entry.level, colors)} wrap="truncate">
              {entry.message}
            </Text>
            {entry.data && Object.keys(entry.data).length > 0 && (
              <Text color={colors.textMuted} dimColor>
                {formatData(entry.data)}
              </Text>
            )}
          </Box>
        ))}
      </Box>
    </Box>
  );
});

// =============================================================================
// DEBUG BUFFER HOOK
// =============================================================================

/**
 * Hook to manage a ring buffer of debug entries.
 */
export function useDebugBuffer(maxSize: number = 100) {
  const [entries, setEntries] = useState<DebugEntry[]>([]);
  const idCounterRef = useRef(0);

  const addEntry = (
    level: DebugEntry['level'],
    message: string,
    data?: Record<string, unknown>
  ) => {
    const entry: DebugEntry = {
      id: `debug-${++idCounterRef.current}`,
      timestamp: new Date(),
      level,
      message,
      data,
    };

    setEntries(prev => {
      const newEntries = [...prev, entry];
      // Keep only the last maxSize entries
      return newEntries.slice(-maxSize);
    });
  };

  const clear = () => setEntries([]);

  return {
    entries,
    addEntry,
    clear,
    debug: (msg: string, data?: Record<string, unknown>) => addEntry('debug', msg, data),
    info: (msg: string, data?: Record<string, unknown>) => addEntry('info', msg, data),
    warn: (msg: string, data?: Record<string, unknown>) => addEntry('warn', msg, data),
    error: (msg: string, data?: Record<string, unknown>) => addEntry('error', msg, data),
  };
}

export default DebugPanel;
