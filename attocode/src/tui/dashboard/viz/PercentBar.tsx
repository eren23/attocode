import { Box, Text } from 'ink';
import React from 'react';

interface PercentBarProps {
  percent: number;
  width?: number;
  color?: string;
  label?: string;
}

export function PercentBar({ percent, width = 20, color = 'green', label }: PercentBarProps): React.ReactElement {
  const clamped = Math.max(0, Math.min(100, percent));
  const filled = Math.round((clamped / 100) * width);
  const empty = width - filled;
  return (
    <Box>
      {label && <Text>{label} </Text>}
      <Text>[</Text>
      <Text color={clamped > 90 ? 'red' : clamped > 70 ? 'yellow' : color}>{'█'.repeat(filled)}</Text>
      <Text dimColor>{'░'.repeat(empty)}</Text>
      <Text>] </Text>
      <Text bold>{Math.round(clamped)}%</Text>
    </Box>
  );
}
