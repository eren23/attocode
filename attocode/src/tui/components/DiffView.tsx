/**
 * DiffView Component
 *
 * Displays unified diff with color coding for additions/deletions.
 * Can show collapsed summary (+N/-M) or expanded full diff.
 */

import React, { memo } from 'react';
import { Box, Text } from 'ink';

interface DiffViewProps {
  /** The unified diff string */
  diff: string;
  /** Whether to show full diff (true) or just summary (false) */
  expanded: boolean;
  /** Maximum lines to show in expanded view */
  maxLines?: number;
}

/**
 * Parse diff statistics from a unified diff string.
 */
function parseDiffStats(diff: string): { additions: number; deletions: number } {
  const lines = diff.split('\n');
  let additions = 0;
  let deletions = 0;

  for (const line of lines) {
    if (line.startsWith('+') && !line.startsWith('+++')) {
      additions++;
    } else if (line.startsWith('-') && !line.startsWith('---')) {
      deletions++;
    }
  }

  return { additions, deletions };
}

/**
 * Get color for a diff line based on its prefix.
 */
function getDiffLineColor(line: string): string {
  if (line.startsWith('+') && !line.startsWith('+++')) {
    return '#98FB98'; // Green for additions
  }
  if (line.startsWith('-') && !line.startsWith('---')) {
    return '#FF6B6B'; // Red for deletions
  }
  if (line.startsWith('@@')) {
    return '#87CEEB'; // Cyan for hunk headers
  }
  if (line.startsWith('---') || line.startsWith('+++')) {
    return '#DDA0DD'; // Purple for file headers
  }
  return '#666666'; // Gray for context lines
}

export const DiffView = memo(function DiffView({
  diff,
  expanded,
  maxLines = 20,
}: DiffViewProps) {
  if (!diff || diff.trim().length === 0) {
    return <Text color="#666666" dimColor>No changes</Text>;
  }

  const stats = parseDiffStats(diff);

  // Collapsed view: just show +N/-M summary
  if (!expanded) {
    return (
      <Text>
        <Text color="#98FB98">+{stats.additions}</Text>
        <Text color="#666666">/</Text>
        <Text color="#FF6B6B">-{stats.deletions}</Text>
      </Text>
    );
  }

  // Expanded view: show the full diff with colors
  const lines = diff.split('\n');
  const displayLines = lines.slice(0, maxLines);
  const hasMore = lines.length > maxLines;

  return (
    <Box flexDirection="column" marginTop={1}>
      {/* Summary header */}
      <Box gap={1}>
        <Text color="#DDA0DD" bold>Diff:</Text>
        <Text color="#98FB98">+{stats.additions}</Text>
        <Text color="#666666">/</Text>
        <Text color="#FF6B6B">-{stats.deletions}</Text>
      </Box>

      {/* Diff content */}
      <Box flexDirection="column" marginLeft={2} marginTop={1}>
        {displayLines.map((line, i) => (
          <Text key={i} color={getDiffLineColor(line)}>
            {line || ' '}
          </Text>
        ))}
        {hasMore && (
          <Text color="#666666" dimColor>
            ... ({lines.length - maxLines} more lines)
          </Text>
        )}
      </Box>
    </Box>
  );
});

export default DiffView;
