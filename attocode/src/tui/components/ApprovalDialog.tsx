/**
 * ApprovalDialog Component
 *
 * Displays permission requests for dangerous tool operations in TUI mode.
 * Supports keyboard shortcuts: Y (approve), N (deny), D (deny with reason)
 */

import { memo } from 'react';
import { Box, Text } from 'ink';
import type { ThemeColors } from '../types.js';

export interface ApprovalRequest {
  id: string;
  tool: string;
  args: Record<string, unknown>;
  risk: 'low' | 'moderate' | 'high' | 'critical';
  context: string;
}

export interface ApprovalDialogProps {
  visible: boolean;
  request: ApprovalRequest | null;
  onApprove: () => void;
  onDeny: (reason?: string) => void;
  colors: ThemeColors;
  /** Whether in "deny with reason" mode (show input prompt) */
  denyReasonMode?: boolean;
  /** Current deny reason being typed */
  denyReason?: string;
}

/**
 * Format tool arguments for display (truncated)
 */
function formatArgs(args: Record<string, unknown>, maxLength = 120): string {
  const entries = Object.entries(args);
  if (entries.length === 0) return '(no arguments)';

  const parts: string[] = [];
  for (const [key, value] of entries) {
    let valStr: string;
    if (typeof value === 'string') {
      valStr = value.length > 50 ? `"${value.slice(0, 47)}..."` : `"${value}"`;
    } else if (value === null || value === undefined) {
      valStr = String(value);
    } else {
      const json = JSON.stringify(value);
      valStr = json.length > 50 ? json.slice(0, 47) + '...' : json;
    }
    parts.push(`${key}: ${valStr}`);
  }

  const result = parts.join(', ');
  return result.length > maxLength ? result.slice(0, maxLength - 3) + '...' : result;
}

/**
 * Get risk level styling
 */
function getRiskStyle(risk: ApprovalRequest['risk']): { color: string; icon: string } {
  switch (risk) {
    case 'critical':
      return { color: '#FF4444', icon: '!!' };
    case 'high':
      return { color: '#FF6B6B', icon: '!' };
    case 'moderate':
      return { color: '#FFD700', icon: '*' };
    case 'low':
    default:
      return { color: '#87CEEB', icon: '-' };
  }
}

export const ApprovalDialog = memo(function ApprovalDialog({
  visible,
  request,
  colors,
  denyReasonMode = false,
  denyReason = '',
}: ApprovalDialogProps) {
  if (!visible || !request) return null;

  const riskStyle = getRiskStyle(request.risk);
  const argsDisplay = formatArgs(request.args);

  return (
    <Box
      flexDirection="column"
      borderStyle="double"
      borderColor={riskStyle.color}
      paddingX={1}
      paddingY={0}
      marginBottom={1}
    >
      {/* Header */}
      <Box gap={1}>
        <Text color={riskStyle.color} bold>
          [{riskStyle.icon}] APPROVAL REQUIRED
        </Text>
        <Text color={colors.textMuted} dimColor>
          ({request.risk} risk)
        </Text>
      </Box>

      {/* Tool name */}
      <Box marginTop={1} gap={1}>
        <Text color={colors.textMuted}>Tool:</Text>
        <Text color="#DDA0DD" bold>
          {request.tool}
        </Text>
      </Box>

      {/* Arguments */}
      <Box gap={1}>
        <Text color={colors.textMuted}>Args:</Text>
        <Text color={colors.text} wrap="truncate">
          {argsDisplay}
        </Text>
      </Box>

      {/* Context */}
      {request.context && (
        <Box marginTop={1}>
          <Text color={colors.textMuted} dimColor wrap="wrap">
            {request.context.length > 200 ? request.context.slice(0, 197) + '...' : request.context}
          </Text>
        </Box>
      )}

      {/* Action prompt */}
      <Box marginTop={1} gap={2}>
        {denyReasonMode ? (
          <Box gap={1}>
            <Text color={colors.warning}>Deny reason:</Text>
            <Text color={colors.text}>{denyReason}</Text>
            <Text color={colors.textMuted} dimColor>
              (Enter to confirm, Esc to cancel)
            </Text>
          </Box>
        ) : (
          <>
            <Text color="#98FB98" bold>
              [Y]
            </Text>
            <Text color={colors.text}>Approve</Text>
            <Text color={colors.textMuted}>|</Text>
            <Text color="#87CEEB" bold>
              [A]
            </Text>
            <Text color={colors.text}>Always</Text>
            <Text color={colors.textMuted}>|</Text>
            <Text color="#FF6B6B" bold>
              [N]
            </Text>
            <Text color={colors.text}>Deny</Text>
            <Text color={colors.textMuted}>|</Text>
            <Text color="#FFD700" bold>
              [D]
            </Text>
            <Text color={colors.text}>Deny with reason</Text>
          </>
        )}
      </Box>
    </Box>
  );
});

export default ApprovalDialog;
