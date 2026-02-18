/**
 * TransparencyPanel Component
 *
 * Memoized panel showing routing, policy, context health, and memory info.
 * Extracted from TUIApp to prevent re-renders when other TUIApp state changes.
 */

import { memo } from 'react';
import { Box, Text } from 'ink';
import type { ThemeColors } from '../types.js';
import type { TransparencyState } from '../transparency-aggregator.js';

export interface TransparencyPanelProps {
  transparencyState: TransparencyState | null;
  expanded: boolean;
  colors: ThemeColors;
}

export const TransparencyPanel = memo(
  function TransparencyPanel({ transparencyState, expanded, colors }: TransparencyPanelProps) {
    if (!expanded || !transparencyState) return null;

    return (
      <Box
        flexDirection="column"
        marginBottom={1}
        borderStyle="single"
        borderColor={colors.border}
        paddingX={1}
      >
        <Text color={colors.accent} bold>
          [v] Transparency Panel
        </Text>
        <Box marginLeft={2} flexDirection="column">
          <Text color={colors.text}>REASONING</Text>
          {transparencyState.lastRouting ? (
            <>
              <Text color={colors.textMuted}>
                {' '}
                Routing: {transparencyState.lastRouting.model}
              </Text>
              <Text color={colors.textMuted}> {transparencyState.lastRouting.reason}</Text>
            </>
          ) : (
            <Text color={colors.textMuted}> Routing: (no routing decisions yet)</Text>
          )}
          {transparencyState.lastPolicy && (
            <Text
              color={
                transparencyState.lastPolicy.decision === 'blocked'
                  ? colors.error
                  : transparencyState.lastPolicy.decision === 'prompted'
                    ? colors.warning
                    : colors.success
              }
            >
              Policy:{' '}
              {transparencyState.lastPolicy.decision === 'allowed'
                ? '+'
                : transparencyState.lastPolicy.decision === 'blocked'
                  ? 'x'
                  : '?'}{' '}
              {transparencyState.lastPolicy.tool}
            </Text>
          )}
        </Box>
        <Box marginLeft={2} marginTop={1} flexDirection="column">
          <Text color={colors.text}>CONTEXT</Text>
          {transparencyState.contextHealth ? (
            <>
              <Text color={colors.textMuted}>
                {'  [' +
                  '='.repeat(
                    Math.round((transparencyState.contextHealth.percentUsed / 100) * 20),
                  ) +
                  '-'.repeat(
                    20 - Math.round((transparencyState.contextHealth.percentUsed / 100) * 20),
                  ) +
                  '] ' +
                  transparencyState.contextHealth.percentUsed +
                  '%'}
              </Text>
              <Text color={colors.textMuted}>
                {'  ' +
                  (transparencyState.contextHealth.currentTokens / 1000).toFixed(1) +
                  'k / ' +
                  (transparencyState.contextHealth.maxTokens / 1000).toFixed(0) +
                  'k tokens'}
              </Text>
              <Text color={colors.textMuted}>
                {'  ~' +
                  transparencyState.contextHealth.estimatedExchanges +
                  ' exchanges remaining'}
              </Text>
            </>
          ) : (
            <Text color={colors.textMuted}> (no context data yet)</Text>
          )}
        </Box>
        {transparencyState.activeLearnings.length > 0 && (
          <Box marginLeft={2} marginTop={1} flexDirection="column">
            <Text color={colors.text}>MEMORY</Text>
            <Text color={colors.textMuted}>
              {' '}
              Learnings applied: {transparencyState.activeLearnings.length}
            </Text>
          </Box>
        )}
      </Box>
    );
  },
  (prevProps, nextProps) => {
    // Skip re-render if expanded state and transparency data haven't changed
    if (prevProps.expanded !== nextProps.expanded) return false;
    if (prevProps.colors !== nextProps.colors) return false;
    if (!prevProps.expanded && !nextProps.expanded) return true; // Both hidden
    // Check transparency state identity (reference equality is sufficient)
    if (prevProps.transparencyState !== nextProps.transparencyState) return false;
    return true;
  },
);
