/**
 * PlanPanel Component
 *
 * Displays the current interactive plan with step progress indicators.
 * Shows plan goal, step list with status icons, and current step highlight.
 */

import { memo } from 'react';
import { Box, Text } from 'ink';
import type { ThemeColors } from '../types.js';

export interface PlanStep {
  id: string;
  number: number;
  description: string;
  status: 'pending' | 'in_progress' | 'completed' | 'failed' | 'skipped';
}

export interface ActivePlan {
  id: string;
  goal: string;
  steps: PlanStep[];
  status: string;
  currentStepIndex: number;
}

export interface PlanPanelProps {
  plan: ActivePlan | null;
  expanded: boolean;
  colors: ThemeColors;
}

function stepIcon(status: PlanStep['status']): string {
  switch (status) {
    case 'completed': return '[x]';
    case 'in_progress': return '[>]';
    case 'failed': return '[!]';
    case 'skipped': return '[-]';
    default: return '[ ]';
  }
}

function stepColor(status: PlanStep['status'], colors: ThemeColors): string {
  switch (status) {
    case 'completed': return '#98FB98';
    case 'in_progress': return '#87CEEB';
    case 'failed': return '#FF6B6B';
    case 'skipped': return colors.textMuted;
    default: return colors.text;
  }
}

export const PlanPanel = memo(function PlanPanel({
  plan,
  expanded,
  colors,
}: PlanPanelProps) {
  if (!plan || !expanded) return null;

  const completedCount = plan.steps.filter(s => s.status === 'completed').length;
  const totalSteps = plan.steps.length;

  return (
    <Box
      flexDirection="column"
      borderStyle="single"
      borderColor="#87CEEB"
      paddingX={1}
      paddingY={0}
      marginBottom={1}
    >
      <Box gap={1}>
        <Text color="#87CEEB" bold>Plan</Text>
        <Text color={colors.textMuted}>
          ({completedCount}/{totalSteps} steps | {plan.status})
        </Text>
      </Box>

      <Box marginTop={0} flexDirection="column">
        <Text color={colors.text} wrap="wrap" dimColor>{plan.goal}</Text>
      </Box>

      <Box marginTop={1} flexDirection="column">
        {plan.steps.map((step) => (
          <Box key={step.id} gap={1}>
            <Text color={stepColor(step.status, colors)}>
              {stepIcon(step.status)}
            </Text>
            <Text
              color={stepColor(step.status, colors)}
              bold={step.status === 'in_progress'}
              dimColor={step.status === 'skipped'}
            >
              {step.number}. {step.description}
            </Text>
          </Box>
        ))}
      </Box>
    </Box>
  );
}, (prev, next) => {
  if (prev.expanded !== next.expanded) return false;
  if (!prev.expanded && !next.expanded) return true;
  if (prev.plan !== next.plan) return false;
  if (prev.colors !== next.colors) return false;
  return true;
});
