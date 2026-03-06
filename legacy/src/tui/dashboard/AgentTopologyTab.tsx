import { Box, Text } from 'ink';
import React from 'react';
import { AsciiTreeRenderer, type TreeNodeData } from './viz/index.js';

interface AgentTopologyTabProps {
  agents?: Array<{
    id: string;
    type: string;
    status: string;
    parentId?: string;
    tokensUsed?: number;
  }>;
}

function buildAgentTree(agents: AgentTopologyTabProps['agents']): TreeNodeData[] {
  if (!agents || agents.length === 0) return [];

  const agentMap = new Map(agents.map(a => [a.id, a]));
  const roots: TreeNodeData[] = [];
  const childMap = new Map<string, TreeNodeData[]>();

  for (const agent of agents) {
    const node: TreeNodeData = {
      label: `${agent.type} (${agent.id.slice(0, 8)})`,
      status: agent.status === 'completed' ? 'success' : agent.status === 'failed' ? 'error' : 'pending',
      metrics: agent.tokensUsed ? `${agent.tokensUsed.toLocaleString()} tok` : undefined,
      children: [],
    };

    if (agent.parentId && agentMap.has(agent.parentId)) {
      if (!childMap.has(agent.parentId)) childMap.set(agent.parentId, []);
      childMap.get(agent.parentId)!.push(node);
    } else {
      roots.push(node);
    }

    childMap.set(agent.id, node.children!);
  }

  // Wire children
  for (const agent of agents) {
    const children = childMap.get(agent.id);
    if (children) {
      const parentNode = roots.find(r => r.label.includes(agent.id.slice(0, 8)))
        || findNode(roots, agent.id.slice(0, 8));
      if (parentNode) parentNode.children = children;
    }
  }

  return roots;
}

function findNode(nodes: TreeNodeData[], idFragment: string): TreeNodeData | null {
  for (const node of nodes) {
    if (node.label.includes(idFragment)) return node;
    if (node.children) {
      const found = findNode(node.children, idFragment);
      if (found) return found;
    }
  }
  return null;
}

export function AgentTopologyTab({ agents }: AgentTopologyTabProps): React.ReactElement {
  if (!agents || agents.length === 0) {
    return (
      <Box flexDirection="column" paddingX={1}>
        <Text bold>Agent Topology</Text>
        <Text dimColor>No agent hierarchy data available.</Text>
        <Text dimColor>This view shows the parent-child relationship between agents and subagents.</Text>
      </Box>
    );
  }

  const tree = buildAgentTree(agents);

  return (
    <Box flexDirection="column" paddingX={1}>
      <Text bold underline>Agent Topology ({agents.length} agents)</Text>
      <AsciiTreeRenderer nodes={tree} maxDepth={6} />
    </Box>
  );
}
