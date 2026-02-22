import { Box, Text } from 'ink';
import React from 'react';

interface ASCIITableProps {
  headers: string[];
  rows: string[][];
  columnWidths?: number[];
}

export function ASCIITable({ headers, rows, columnWidths }: ASCIITableProps): React.ReactElement {
  const widths = columnWidths ?? headers.map((h, i) => {
    const colMax = Math.max(h.length, ...rows.map(r => (r[i] || '').length));
    return Math.min(colMax, 40);
  });

  const formatRow = (cells: string[]): string => {
    return cells.map((cell, i) => {
      const w = widths[i] || 10;
      return (cell || '').slice(0, w).padEnd(w);
    }).join(' │ ');
  };

  const separator = widths.map(w => '─'.repeat(w)).join('─┼─');

  return (
    <Box flexDirection="column">
      <Text bold>{formatRow(headers)}</Text>
      <Text dimColor>{separator}</Text>
      {rows.map((row, idx) => (
        <Text key={idx}>{formatRow(row)}</Text>
      ))}
    </Box>
  );
}
