import { Box, Text } from 'ink';
import React from 'react';
import type { SessionSummary } from '../hooks/use-session-browser.js';

interface SessionListTabProps {
  sessions: SessionSummary[];
  loading: boolean;
  selectedIndex: number;
  filterText: string;
  onSelect: (sessionId: string) => void;
}

function formatDate(d: Date): string {
  return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

export function SessionListTab({ sessions, loading, selectedIndex, filterText }: SessionListTabProps): React.ReactElement {
  if (loading) {
    return <Box paddingX={1}><Text>Loading sessions...</Text></Box>;
  }

  if (sessions.length === 0) {
    return (
      <Box paddingX={1} flexDirection="column">
        <Text>No sessions found in .traces/</Text>
        {filterText && <Text dimColor>Filter: "{filterText}" - try clearing the filter</Text>}
      </Box>
    );
  }

  const PAGE_SIZE = 15;
  const startIdx = Math.max(0, selectedIndex - Math.floor(PAGE_SIZE / 2));
  const visible = sessions.slice(startIdx, startIdx + PAGE_SIZE);

  return (
    <Box flexDirection="column" paddingX={1}>
      <Box marginBottom={1}>
        <Text bold>{sessions.length} sessions</Text>
        {filterText && <Text dimColor> (filtered: "{filterText}")</Text>}
        <Text dimColor>  [Up/Down: navigate, Enter: open, /: search, c: compare]</Text>
      </Box>

      {/* Header */}
      <Box>
        <Text bold>{'  '}</Text>
        <Text bold>{'Date'.padEnd(18)}</Text>
        <Text bold>{'Model'.padEnd(20)}</Text>
        <Text bold>{'Iters'.padEnd(7)}</Text>
        <Text bold>{'Tokens'.padEnd(9)}</Text>
        <Text bold>{'Cost'.padEnd(9)}</Text>
        <Text bold>{'Status'.padEnd(10)}</Text>
        <Text bold>Task</Text>
      </Box>
      <Text dimColor>{'─'.repeat(100)}</Text>

      {visible.map((session, idx) => {
        const absIdx = startIdx + idx;
        const isSelected = absIdx === selectedIndex;
        const statusColor = session.status === 'completed' ? 'green' : session.status === 'failed' ? 'red' : 'yellow';

        return (
          <Box key={session.id}>
            <Text color={isSelected ? 'blue' : undefined} bold={isSelected}>
              {isSelected ? '> ' : '  '}
              {formatDate(session.startTime).padEnd(18)}
              {session.model.slice(0, 18).padEnd(20)}
              {String(session.iterations).padEnd(7)}
              {formatTokens(session.totalTokens).padEnd(9)}
              {'$' + session.totalCost.toFixed(3).padEnd(8)}
            </Text>
            <Text color={statusColor}>{session.status.padEnd(10)}</Text>
            <Text dimColor={!isSelected}>{session.task.slice(0, 40)}</Text>
          </Box>
        );
      })}
    </Box>
  );
}
