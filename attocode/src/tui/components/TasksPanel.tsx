/**
 * Tasks Panel Component
 *
 * Displays task list in an anchored panel above the input box.
 * Similar to Claude Code's task tracking interface.
 *
 * Features:
 * - Real-time status updates for tasks
 * - Dependency visualization (blocked by)
 * - Active form display for in_progress tasks
 * - Toggle visibility with Alt+K
 */

import { memo } from 'react';
import { Box, Text } from 'ink';
import type { ThemeColors } from '../types.js';
import type { Task, TaskStatus } from '../../integrations/tasks/task-manager.js';

// =============================================================================
// TYPES
// =============================================================================

export interface TasksPanelProps {
  /** List of tasks to display */
  tasks: Task[];
  /** Theme colors */
  colors: ThemeColors;
  /** Whether the panel is expanded/visible */
  expanded: boolean;
}

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

/**
 * Get status icon for task state.
 */
function getStatusIcon(status: TaskStatus, isBlocked: boolean): string {
  if (isBlocked) return '◌';  // Blocked
  switch (status) {
    case 'pending':
      return '○';
    case 'in_progress':
      return '●';
    case 'completed':
      return '✓';
    default:
      return '○';
  }
}

/**
 * Get color for task status.
 */
function getStatusColor(status: TaskStatus, isBlocked: boolean, colors: ThemeColors): string {
  if (isBlocked) return colors.warning;
  switch (status) {
    case 'pending':
      return colors.textMuted;
    case 'in_progress':
      return colors.info;
    case 'completed':
      return colors.success;
    default:
      return colors.textMuted;
  }
}

/**
 * Truncate subject for display.
 */
function truncateSubject(subject: string, maxLength: number = 40): string {
  if (subject.length <= maxLength) return subject;
  return subject.slice(0, maxLength - 3) + '...';
}

// =============================================================================
// SINGLE TASK ITEM
// =============================================================================

interface TaskItemProps {
  task: Task;
  colors: ThemeColors;
  allTasks: Task[];
}

const TaskItem = memo(function TaskItem({ task, colors, allTasks }: TaskItemProps) {
  // Check if task is blocked by any non-completed task
  const isBlocked = task.blockedBy.some(blockerId => {
    const blocker = allTasks.find(t => t.id === blockerId);
    return blocker && blocker.status !== 'completed';
  });

  const icon = getStatusIcon(task.status, isBlocked);
  const statusColor = getStatusColor(task.status, isBlocked, colors);
  const subjectPreview = truncateSubject(task.subject);

  // Build blocked by info
  let blockedByInfo = '';
  if (isBlocked && task.blockedBy.length > 0) {
    const blockerIds = task.blockedBy.slice(0, 2).join(', ');
    blockedByInfo = task.blockedBy.length > 2
      ? ` (blocked by: ${blockerIds}, +${task.blockedBy.length - 2})`
      : ` (blocked by: ${blockerIds})`;
  }

  return (
    <Box flexDirection="column">
      <Box gap={1}>
        <Text color={statusColor}>{icon}</Text>
        <Text color={colors.textMuted} dimColor>{task.id}</Text>
        <Text color={colors.text}>{subjectPreview}</Text>
        {blockedByInfo && (
          <Text color={colors.warning} dimColor>{blockedByInfo}</Text>
        )}
      </Box>
      {/* Show activeForm for in_progress tasks */}
      {task.status === 'in_progress' && task.activeForm && (
        <Box marginLeft={3}>
          <Text color={colors.info} dimColor>{task.activeForm}...</Text>
        </Box>
      )}
    </Box>
  );
});

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export const TasksPanel = memo(function TasksPanel({
  tasks,
  colors,
  expanded,
}: TasksPanelProps) {
  // Filter out deleted tasks
  const visibleTasks = tasks.filter(t => t.status !== 'deleted');

  // Don't render if no tasks or not expanded
  if (!expanded || visibleTasks.length === 0) {
    return null;
  }

  // Count by status
  const pending = visibleTasks.filter(t => t.status === 'pending').length;
  const inProgress = visibleTasks.filter(t => t.status === 'in_progress').length;
  const completed = visibleTasks.filter(t => t.status === 'completed').length;

  // Show most recent tasks (last 5)
  const recentTasks = visibleTasks.slice(-5);

  // Determine border color based on activity
  const hasActive = inProgress > 0;

  return (
    <Box
      flexDirection="column"
      marginBottom={1}
      borderStyle="single"
      borderColor={hasActive ? colors.info : colors.border}
      paddingX={1}
    >
      {/* Header */}
      <Box justifyContent="space-between">
        <Text color={colors.accent} bold>
          TASKS [{pending} pending, {inProgress} in_progress, {completed} completed]
        </Text>
        <Text color={colors.textMuted} dimColor>Alt+K to hide</Text>
      </Box>

      {/* Task list */}
      <Box flexDirection="column" marginTop={1}>
        {recentTasks.map(task => (
          <TaskItem key={task.id} task={task} colors={colors} allTasks={visibleTasks} />
        ))}
      </Box>
    </Box>
  );
});

export default TasksPanel;
