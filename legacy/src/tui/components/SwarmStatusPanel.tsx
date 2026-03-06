/**
 * Swarm Status Panel Component
 *
 * Displays live swarm execution status in the TUI.
 * Shows wave progress, active workers, queue stats, and budget usage.
 *
 * Features:
 * - Wave progress bar with percentage
 * - Active workers table with model, task, and elapsed time
 * - Queue stats (ready, running, done, failed, skipped)
 * - Budget bar (tokens and cost)
 * - Auto-hides when no swarm is active
 * - Toggle visibility with Alt+W
 */

import { memo } from 'react';
import { Box, Text } from 'ink';
import type { ThemeColors } from '../types.js';
import type { SwarmStatus, SwarmWorkerStatus } from '../../integrations/swarm/types.js';

// =============================================================================
// TYPES
// =============================================================================

export interface SwarmStatusPanelProps {
  /** Live swarm status (null when no swarm is active) */
  status: SwarmStatus | null;
  /** Theme colors */
  colors: ThemeColors;
  /** Whether the panel is expanded/visible */
  expanded: boolean;
}

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

/**
 * Build a text-based progress bar.
 */
function progressBar(current: number, total: number, width: number = 20): string {
  if (total === 0) return '[' + '-'.repeat(width) + ']';
  const pct = Math.min(1, current / total);
  const filled = Math.round(pct * width);
  const empty = width - filled;
  return '[' + '\u2588'.repeat(filled) + '\u2591'.repeat(empty) + ']';
}

/**
 * Format token count for display.
 */
function formatTokens(tokens: number): string {
  if (tokens >= 1_000_000) {
    return `${(tokens / 1_000_000).toFixed(1)}M`;
  }
  if (tokens >= 1000) {
    return `${(tokens / 1000).toFixed(0)}k`;
  }
  return String(tokens);
}

/**
 * Format elapsed time from startedAt timestamp.
 */
function formatElapsed(startedAt: number): string {
  const elapsed = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
  if (elapsed < 60) return `${elapsed}s`;
  const minutes = Math.floor(elapsed / 60);
  const seconds = elapsed % 60;
  return `${minutes}m${seconds}s`;
}

/**
 * Get phase display text and color.
 */
function getPhaseInfo(phase: SwarmStatus['phase']): { text: string; color: string } {
  switch (phase) {
    case 'decomposing':
      return { text: 'Decomposing task...', color: '#DDA0DD' };
    case 'scheduling':
      return { text: 'Scheduling waves...', color: '#DDA0DD' };
    case 'planning':
      return { text: 'Planning execution...', color: '#DDA0DD' };
    case 'executing':
      return { text: 'Executing', color: '#87CEEB' };
    case 'reviewing':
      return { text: 'Reviewing outputs...', color: '#DDA0DD' };
    case 'verifying':
      return { text: 'Verifying integration...', color: '#DDA0DD' };
    case 'synthesizing':
      return { text: 'Synthesizing results...', color: '#DDA0DD' };
    case 'completed':
      return { text: 'Completed', color: '#98FB98' };
    case 'failed':
      return { text: 'Failed', color: '#FF6B6B' };
  }
}

/**
 * Get short model name from full model ID.
 */
function shortModelName(model: string): string {
  const parts = model.split('/');
  const name = parts[parts.length - 1] || model;
  // Truncate to 20 chars
  return name.length > 20 ? name.slice(0, 17) + '...' : name;
}

// =============================================================================
// WORKER ROW
// =============================================================================

interface WorkerRowProps {
  worker: SwarmWorkerStatus;
  colors: ThemeColors;
}

const WorkerRow = memo(function WorkerRow({ worker, colors }: WorkerRowProps) {
  const elapsed = formatElapsed(worker.startedAt);
  const taskPreview =
    worker.taskDescription.length > 40
      ? worker.taskDescription.slice(0, 37) + '...'
      : worker.taskDescription;

  return (
    <Box gap={1}>
      <Text color={colors.info}>{'●'}</Text>
      <Text color={colors.accent} bold>
        {worker.workerName.padEnd(10)}
      </Text>
      <Text color={colors.textMuted} dimColor>
        ({shortModelName(worker.model)})
      </Text>
      <Text color={colors.text}>{taskPreview}</Text>
      <Text color={colors.textMuted} dimColor>
        [{elapsed}]
      </Text>
    </Box>
  );
});

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export const SwarmStatusPanel = memo(function SwarmStatusPanel({
  status,
  colors,
  expanded,
}: SwarmStatusPanelProps) {
  // Don't render if no swarm status or not expanded
  if (!expanded || !status) {
    return null;
  }

  const phaseInfo = getPhaseInfo(status.phase);
  const isActive =
    status.phase === 'executing' ||
    status.phase === 'decomposing' ||
    status.phase === 'scheduling' ||
    status.phase === 'synthesizing';
  const waveProgress =
    status.totalWaves > 0 ? Math.round((status.currentWave / status.totalWaves) * 100) : 0;

  const { queue, budget } = status;
  const tokenPct =
    budget.tokensTotal > 0 ? Math.round((budget.tokensUsed / budget.tokensTotal) * 100) : 0;
  const costStr = `$${budget.costUsed.toFixed(4)}/$${budget.costTotal.toFixed(2)}`;

  return (
    <Box
      flexDirection="column"
      marginBottom={1}
      borderStyle="single"
      borderColor={isActive ? '#DDA0DD' : colors.border}
      paddingX={1}
    >
      {/* Header */}
      <Box justifyContent="space-between">
        <Box gap={1}>
          <Text color="#DDA0DD" bold>
            SWARM
          </Text>
          <Text color={phaseInfo.color}>{phaseInfo.text}</Text>
        </Box>
        <Text color={colors.textMuted} dimColor>
          Alt+W to hide
        </Text>
      </Box>

      {/* Wave Progress */}
      {status.totalWaves > 0 && (
        <Box marginTop={1} gap={1}>
          <Text color={colors.text}>
            Wave {status.currentWave}/{status.totalWaves}
          </Text>
          <Text color={isActive ? '#DDA0DD' : colors.success}>
            {progressBar(status.currentWave, status.totalWaves, 16)} {waveProgress}%
          </Text>
        </Box>
      )}

      {/* Queue Stats */}
      <Box gap={2} marginTop={1}>
        <Text color={colors.textMuted}>Queue:</Text>
        {queue.ready > 0 && <Text color={colors.text}>Ready: {queue.ready}</Text>}
        {queue.running > 0 && <Text color={colors.info}>Running: {queue.running}</Text>}
        <Text color={colors.success}>Done: {queue.completed}</Text>
        {queue.failed > 0 && <Text color={colors.error}>Failed: {queue.failed}</Text>}
        {queue.skipped > 0 && <Text color={colors.warning}>Skipped: {queue.skipped}</Text>}
        <Text color={colors.textMuted} dimColor>
          Total: {queue.total}
        </Text>
      </Box>

      {/* Active Workers */}
      {status.activeWorkers.length > 0 && (
        <Box flexDirection="column" marginTop={1}>
          <Text color={colors.textMuted}>Workers ({status.activeWorkers.length} active):</Text>
          {status.activeWorkers.slice(0, 5).map((worker) => (
            <WorkerRow key={worker.taskId} worker={worker} colors={colors} />
          ))}
          {status.activeWorkers.length > 5 && (
            <Text color={colors.textMuted} dimColor>
              {' '}
              ...and {status.activeWorkers.length - 5} more
            </Text>
          )}
        </Box>
      )}

      {/* Budget */}
      <Box gap={1} marginTop={1}>
        <Text color={colors.textMuted}>Budget:</Text>
        <Text color={tokenPct > 80 ? colors.warning : colors.text}>
          {formatTokens(budget.tokensUsed)}/{formatTokens(budget.tokensTotal)} tokens
        </Text>
        <Text color={tokenPct > 80 ? colors.warning : colors.textMuted} dimColor>
          {progressBar(budget.tokensUsed, budget.tokensTotal, 10)} {tokenPct}%
        </Text>
        <Text color={colors.textMuted} dimColor>
          |
        </Text>
        <Text
          color={budget.costUsed > budget.costTotal * 0.8 ? colors.warning : '#98FB98'}
          dimColor
        >
          {costStr}
        </Text>
      </Box>
    </Box>
  );
});

export default SwarmStatusPanel;
