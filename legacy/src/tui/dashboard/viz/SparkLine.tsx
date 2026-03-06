import { Text } from 'ink';
import React from 'react';

const BLOCKS = ['▁', '▂', '▃', '▄', '▅', '▆', '▇', '█'];

interface SparkLineProps {
  data: number[];
  width?: number;
  color?: string;
}

export function SparkLine({ data, width, color }: SparkLineProps): React.ReactElement | null {
  if (data.length === 0) return null;
  const displayData = width && data.length > width ? data.slice(-width) : data;
  const min = Math.min(...displayData);
  const max = Math.max(...displayData);
  const range = max - min || 1;
  const chars = displayData.map(v => {
    const idx = Math.min(7, Math.floor(((v - min) / range) * 7));
    return BLOCKS[idx];
  }).join('');
  return <Text color={color}>{chars}</Text>;
}
