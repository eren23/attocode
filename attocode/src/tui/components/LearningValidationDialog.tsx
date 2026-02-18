/**
 * LearningValidationDialog Component
 *
 * Displays proposed learnings from the learning store for user validation.
 * Keyboard shortcuts: Y (approve), N (reject), S (skip)
 */

import { memo } from 'react';
import { Box, Text } from 'ink';
import type { ThemeColors } from '../types.js';

export interface ProposedLearning {
  id: string;
  type: string;
  description: string;
  details?: string;
  categories: string[];
  confidence: number;
}

export interface LearningValidationDialogProps {
  visible: boolean;
  learning: ProposedLearning | null;
  onApprove: () => void;
  onReject: () => void;
  onSkip: () => void;
  colors: ThemeColors;
}

function formatConfidence(confidence: number): string {
  return `${(confidence * 100).toFixed(0)}%`;
}

function confidenceColor(confidence: number): string {
  if (confidence >= 0.8) return '#98FB98';
  if (confidence >= 0.5) return '#FFD700';
  return '#FF6B6B';
}

export const LearningValidationDialog = memo(function LearningValidationDialog({
  visible,
  learning,
  onApprove: _onApprove,
  onReject: _onReject,
  onSkip: _onSkip,
  colors,
}: LearningValidationDialogProps) {
  if (!visible || !learning) return null;

  return (
    <Box
      flexDirection="column"
      borderStyle="double"
      borderColor="#87CEEB"
      paddingX={1}
      paddingY={0}
      marginBottom={1}
    >
      <Box gap={1}>
        <Text color="#87CEEB" bold>
          {'[?] LEARNING PROPOSED'}
        </Text>
        <Text color={colors.textMuted}>({learning.type})</Text>
      </Box>

      <Box marginTop={1} flexDirection="column">
        <Text color={colors.text} wrap="wrap">{learning.description}</Text>
        {learning.details && (
          <Box marginTop={0}>
            <Text color={colors.textMuted} wrap="wrap">{learning.details}</Text>
          </Box>
        )}
      </Box>

      <Box marginTop={1} gap={1}>
        <Text color={colors.textMuted}>Confidence:</Text>
        <Text color={confidenceColor(learning.confidence)} bold>
          {formatConfidence(learning.confidence)}
        </Text>
        {learning.categories.length > 0 && (
          <>
            <Text color={colors.textMuted}>|</Text>
            <Text color={colors.textMuted}>
              {learning.categories.join(', ')}
            </Text>
          </>
        )}
      </Box>

      <Box marginTop={1} gap={2}>
        <Text color="#98FB98" bold>[Y]</Text>
        <Text color={colors.text}>Approve</Text>
        <Text color={colors.textMuted}>|</Text>
        <Text color="#FF6B6B" bold>[N]</Text>
        <Text color={colors.text}>Reject</Text>
        <Text color={colors.textMuted}>|</Text>
        <Text color="#FFD700" bold>[S]</Text>
        <Text color={colors.text}>Skip</Text>
      </Box>
    </Box>
  );
}, (prev, next) => {
  if (prev.visible !== next.visible) return false;
  if (!prev.visible && !next.visible) return true;
  if (prev.learning !== next.learning) return false;
  if (prev.colors !== next.colors) return false;
  return true;
});
