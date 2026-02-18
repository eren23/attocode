/**
 * BudgetExtensionDialog Component
 *
 * Displays budget extension requests when the agent's economics system
 * detects that the current budget is insufficient.
 * Keyboard shortcuts: Y (approve), N (deny)
 */

import { memo } from 'react';
import { Box, Text } from 'ink';
import type { ThemeColors } from '../types.js';
import type { ExtensionRequest } from '../../integrations/budget/economics.js';

export interface BudgetExtensionDialogProps {
  visible: boolean;
  request: ExtensionRequest | null;
  onApprove: () => void;
  onDeny: () => void;
  colors: ThemeColors;
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

export const BudgetExtensionDialog = memo(function BudgetExtensionDialog({
  visible,
  request,
  onApprove: _onApprove,
  onDeny: _onDeny,
  colors,
}: BudgetExtensionDialogProps) {
  if (!visible || !request) return null;

  const currentTokens = request.budget.maxTokens;
  const suggestedTokens = request.suggestedExtension.maxTokens ?? currentTokens;
  const increase = suggestedTokens - currentTokens;
  const percentIncrease = currentTokens > 0 ? ((increase / currentTokens) * 100).toFixed(0) : '0';

  const usedPercent = currentTokens > 0
    ? ((request.currentUsage.tokens / currentTokens) * 100).toFixed(0)
    : '0';

  return (
    <Box
      flexDirection="column"
      borderStyle="double"
      borderColor="#FFD700"
      paddingX={1}
      paddingY={0}
      marginBottom={1}
    >
      <Box gap={1}>
        <Text color="#FFD700" bold>
          {'[*] BUDGET EXTENSION REQUEST'}
        </Text>
      </Box>

      <Box marginTop={1} flexDirection="column">
        <Box gap={1}>
          <Text color={colors.textMuted}>Current budget:</Text>
          <Text color={colors.text}>{formatTokens(currentTokens)} tokens</Text>
          <Text color={colors.textMuted}>({usedPercent}% used)</Text>
        </Box>

        <Box gap={1}>
          <Text color={colors.textMuted}>Requested:</Text>
          <Text color="#FFD700">{formatTokens(suggestedTokens)} tokens</Text>
          <Text color={colors.textMuted}>(+{formatTokens(increase)}, {percentIncrease}%)</Text>
        </Box>
      </Box>

      {request.reason && (
        <Box marginTop={1}>
          <Text color={colors.textMuted} wrap="wrap">Reason: {request.reason}</Text>
        </Box>
      )}

      <Box marginTop={1} gap={2}>
        <Text color="#98FB98" bold>[Y]</Text>
        <Text color={colors.text}>Approve</Text>
        <Text color={colors.textMuted}>|</Text>
        <Text color="#FF6B6B" bold>[N]</Text>
        <Text color={colors.text}>Deny</Text>
      </Box>
    </Box>
  );
}, (prev, next) => {
  if (prev.visible !== next.visible) return false;
  if (!prev.visible && !next.visible) return true;
  if (prev.request !== next.request) return false;
  if (prev.colors !== next.colors) return false;
  return true;
});
