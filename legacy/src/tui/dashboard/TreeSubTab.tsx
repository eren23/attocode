import { Box, Text } from 'ink';
import React from 'react';
import { AsciiTreeRenderer, type TreeNodeData } from './viz/index.js';
import type { SessionDetailData } from '../hooks/use-session-detail.js';

interface TreeSubTabProps {
  data: SessionDetailData;
}

function convertToTreeNodeData(node: any): TreeNodeData {
  return {
    label: node.label || node.id || 'unknown',
    status: node.status === 'success' ? 'success' : node.status === 'error' ? 'error' : 'pending',
    metrics: node.durationMs != null ? `${node.durationMs}ms` : undefined,
    children: (node.children || []).map(convertToTreeNodeData),
  };
}

export function TreeSubTab({ data }: TreeSubTabProps): React.ReactElement {
  if (!data.tree) return <Text dimColor>No tree data available</Text>;

  const rootNodes = Array.isArray(data.tree)
    ? data.tree.map(convertToTreeNodeData)
    : data.tree.children
      ? [convertToTreeNodeData(data.tree)]
      : [];

  if (rootNodes.length === 0) return <Text dimColor>Empty tree</Text>;

  return (
    <Box flexDirection="column">
      <Text bold>Execution Tree</Text>
      <AsciiTreeRenderer nodes={rootNodes} maxDepth={8} />
    </Box>
  );
}
