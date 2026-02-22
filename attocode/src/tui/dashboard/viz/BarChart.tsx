import { Box, Text } from 'ink';
import React from 'react';

export interface BarChartItem {
  label: string;
  value: number;
  color?: string;
}

interface BarChartProps {
  items: BarChartItem[];
  maxWidth?: number;
  showValues?: boolean;
}

export function BarChart({ items, maxWidth = 40, showValues = true }: BarChartProps): React.ReactElement {
  const maxVal = Math.max(...items.map(i => i.value), 1);
  const maxLabelLen = Math.max(...items.map(i => i.label.length), 1);

  return (
    <Box flexDirection="column">
      {items.map((item, idx) => {
        const barLen = Math.max(1, Math.round((item.value / maxVal) * maxWidth));
        const bar = '█'.repeat(barLen);
        const pad = ' '.repeat(maxLabelLen - item.label.length);
        return (
          <Box key={idx}>
            <Text>{pad}{item.label} </Text>
            <Text color={item.color || 'blue'}>{bar}</Text>
            {showValues && <Text dimColor> {item.value}</Text>}
          </Box>
        );
      })}
    </Box>
  );
}
