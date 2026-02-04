/**
 * Active Agents Panel Component
 *
 * Displays running subagents in an anchored panel above the input box.
 * Inspired by Claude Code's Task visibility feature.
 *
 * Features:
 * - Real-time status updates for running agents
 * - Token usage per agent
 * - Task preview with truncation
 * - Toggle visibility with Alt+A
 */

import { memo } from 'react';
import { Box, Text } from 'ink';
import type { ThemeColors } from '../types.js';

// =============================================================================
// TYPES
// =============================================================================

export type ActiveAgentStatus = 'running' | 'completed' | 'error' | 'timeout';

export interface ActiveAgent {
  /** Unique agent ID (e.g., "spawn-1234567890") */
  id: string;
  /** Agent type (researcher, coder, reviewer, etc.) */
  type: string;
  /** Task description (truncated for display) */
  task: string;
  /** Current status */
  status: ActiveAgentStatus;
  /** Tokens consumed by this agent */
  tokens: number;
  /** Start timestamp */
  startTime: number;
  /** Current phase (exploring, planning, executing) */
  currentPhase?: string;
  /** Current iteration */
  iteration?: number;
  /** Max iterations */
  maxIterations?: number;
}

export interface ActiveAgentsPanelProps {
  /** List of active agents to display */
  agents: ActiveAgent[];
  /** Theme colors */
  colors: ThemeColors;
  /** Whether the panel is expanded/visible */
  expanded: boolean;
}

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

/**
 * Get status icon for agent state.
 */
function getStatusIcon(status: ActiveAgentStatus): string {
  switch (status) {
    case 'running':
      return '●';
    case 'completed':
      return '✓';
    case 'error':
      return '✗';
    case 'timeout':
      return '⏱';
    default:
      return '○';
  }
}

/**
 * Get color for agent status.
 */
function getStatusColor(status: ActiveAgentStatus, colors: ThemeColors): string {
  switch (status) {
    case 'running':
      return colors.info;
    case 'completed':
      return colors.success;
    case 'error':
      return colors.error;
    case 'timeout':
      return colors.warning;
    default:
      return colors.textMuted;
  }
}

/**
 * Format token count for display.
 */
function formatTokens(tokens: number): string {
  if (tokens >= 1000) {
    return `${(tokens / 1000).toFixed(1)}k`;
  }
  return String(tokens);
}

/**
 * Format elapsed time in human-readable format.
 */
function formatElapsed(startTime: number): string {
  const elapsed = Math.floor((Date.now() - startTime) / 1000);
  if (elapsed < 60) {
    return `${elapsed}s`;
  }
  const minutes = Math.floor(elapsed / 60);
  const seconds = elapsed % 60;
  return `${minutes}m${seconds}s`;
}

/**
 * Truncate task description for display.
 */
function truncateTask(task: string, maxLength: number = 50): string {
  if (task.length <= maxLength) return task;
  return task.slice(0, maxLength - 3) + '...';
}

// =============================================================================
// SINGLE AGENT ITEM
// =============================================================================

interface AgentItemProps {
  agent: ActiveAgent;
  colors: ThemeColors;
}

const AgentItem = memo(function AgentItem({ agent, colors }: AgentItemProps) {
  const icon = getStatusIcon(agent.status);
  const statusColor = getStatusColor(agent.status, colors);
  const elapsed = formatElapsed(agent.startTime);
  const tokens = formatTokens(agent.tokens);
  const taskPreview = truncateTask(agent.task);

  // Build phase/iteration info
  let phaseInfo = '';
  if (agent.status === 'running') {
    if (agent.currentPhase) {
      phaseInfo = ` ${agent.currentPhase}`;
    }
    if (agent.iteration !== undefined && agent.maxIterations !== undefined) {
      phaseInfo += ` (${agent.iteration}/${agent.maxIterations})`;
    }
  }

  return (
    <Box gap={1}>
      <Text color={statusColor}>{icon}</Text>
      <Text color={colors.accent} bold>{agent.type}</Text>
      <Text color={colors.textMuted} dimColor>
        ({agent.id.slice(-7)})
      </Text>
      <Text color={colors.text}>{taskPreview}</Text>
      {agent.status === 'running' && phaseInfo && (
        <Text color={colors.info}>{phaseInfo}</Text>
      )}
      <Text color={colors.textMuted} dimColor>|</Text>
      <Text color={agent.tokens > 3000 ? colors.warning : colors.textMuted} dimColor>
        {tokens} tokens
      </Text>
      <Text color={colors.textMuted} dimColor>|</Text>
      <Text color={colors.textMuted} dimColor>{elapsed}</Text>
    </Box>
  );
});

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export const ActiveAgentsPanel = memo(function ActiveAgentsPanel({
  agents,
  colors,
  expanded,
}: ActiveAgentsPanelProps) {
  // Don't render if no agents or not expanded
  if (!expanded || agents.length === 0) {
    return null;
  }

  // Count by status
  const running = agents.filter(a => a.status === 'running').length;
  const completed = agents.filter(a => a.status === 'completed').length;
  const failed = agents.filter(a => a.status === 'error' || a.status === 'timeout').length;

  // Only show recent agents (last 5)
  const visibleAgents = agents.slice(-5);

  return (
    <Box
      flexDirection="column"
      marginBottom={1}
      borderStyle="single"
      borderColor={running > 0 ? colors.info : colors.border}
      paddingX={1}
    >
      {/* Header */}
      <Box justifyContent="space-between">
        <Text color={colors.accent} bold>
          ACTIVE AGENTS [{running} running, {completed} done{failed > 0 ? `, ${failed} failed` : ''}]
        </Text>
        <Text color={colors.textMuted} dimColor>Alt+A to hide</Text>
      </Box>

      {/* Agent list */}
      <Box flexDirection="column" marginTop={1}>
        {visibleAgents.map(agent => (
          <AgentItem key={agent.id} agent={agent} colors={colors} />
        ))}
      </Box>
    </Box>
  );
});

export default ActiveAgentsPanel;
