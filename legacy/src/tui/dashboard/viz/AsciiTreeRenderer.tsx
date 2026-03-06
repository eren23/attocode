import { Box, Text } from 'ink';
import React from 'react';

export interface TreeNodeData {
  label: string;
  status?: 'success' | 'error' | 'pending';
  children?: TreeNodeData[];
  metrics?: string;
}

interface AsciiTreeRendererProps {
  nodes: TreeNodeData[];
  maxDepth?: number;
}

function statusColor(status?: string): string | undefined {
  if (status === 'success') return 'green';
  if (status === 'error') return 'red';
  if (status === 'pending') return 'yellow';
  return undefined;
}

function renderNode(node: TreeNodeData, prefix: string, isLast: boolean, depth: number, maxDepth: number): React.ReactElement[] {
  const connector = isLast ? '└── ' : '├── ';
  const elements: React.ReactElement[] = [];
  const key = `${prefix}-${node.label}-${depth}`;

  elements.push(
    <Box key={key}>
      <Text dimColor>{prefix}{connector}</Text>
      <Text color={statusColor(node.status)}>{node.label}</Text>
      {node.metrics && <Text dimColor> ({node.metrics})</Text>}
    </Box>
  );

  if (node.children && depth < maxDepth) {
    const childPrefix = prefix + (isLast ? '    ' : '│   ');
    node.children.forEach((child, i) => {
      const childIsLast = i === node.children!.length - 1;
      elements.push(...renderNode(child, childPrefix, childIsLast, depth + 1, maxDepth));
    });
  }

  return elements;
}

export function AsciiTreeRenderer({ nodes, maxDepth = 10 }: AsciiTreeRendererProps): React.ReactElement {
  const elements: React.ReactElement[] = [];
  nodes.forEach((node, i) => {
    elements.push(...renderNode(node, '', i === nodes.length - 1, 0, maxDepth));
  });
  return <Box flexDirection="column">{elements}</Box>;
}
