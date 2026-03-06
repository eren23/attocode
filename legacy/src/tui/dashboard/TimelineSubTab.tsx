import { Box, Text } from 'ink';
import React from 'react';
import type { SessionDetailData } from '../hooks/use-session-detail.js';

interface TimelineSubTabProps {
  data: SessionDetailData;
}

const TYPE_ICONS: Record<string, string> = {
  'llm': '[R]',
  'tool': '[T]',
  'error': '[!]',
  'decision': '[D]',
  'subagent': '[S]',
  'compaction': '[C]',
};

export function TimelineSubTab({ data }: TimelineSubTabProps): React.ReactElement {
  if (!data.timeline) return <Text dimColor>No timeline data available</Text>;

  const entries = Array.isArray(data.timeline) ? data.timeline : data.timeline.entries || [];

  return (
    <Box flexDirection="column">
      <Text bold>Timeline ({entries.length} events)</Text>
      <Text dimColor>{'─'.repeat(80)}</Text>
      {entries.slice(0, 50).map((entry: any, idx: number) => {
        const icon = TYPE_ICONS[entry.type] || '[·]';
        const relTime = entry.relativeMs != null
          ? `+${(entry.relativeMs / 1000).toFixed(1)}s`
          : '';
        const importanceColor = entry.importance === 'high' ? 'yellow' : undefined;

        return (
          <Box key={idx}>
            <Text dimColor>{relTime.padStart(8)} </Text>
            <Text color={importanceColor}>{icon} </Text>
            <Text>{entry.description || entry.type}</Text>
            {entry.durationMs != null && <Text dimColor> ({entry.durationMs}ms)</Text>}
          </Box>
        );
      })}
      {entries.length > 50 && <Text dimColor>... {entries.length - 50} more events</Text>}
    </Box>
  );
}
