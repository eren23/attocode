/**
 * Header Component
 *
 * Displays the application title, model info, and status metrics.
 */

import React from 'react';
import { Box, Text } from 'ink';
import type { StatusDisplay } from '../types.js';
import type { Theme } from '../theme/index.js';

export interface HeaderProps {
  theme: Theme;
  title?: string;
  status: StatusDisplay | null;
  showMetrics?: boolean;
}

export function Header({
  theme,
  title = 'Attocode',
  status,
  showMetrics = true,
}: HeaderProps) {
  const formatTokens = (tokens: number): string => {
    if (tokens >= 1000000) return `${(tokens / 1000000).toFixed(1)}M`;
    if (tokens >= 1000) return `${(tokens / 1000).toFixed(1)}k`;
    return tokens.toString();
  };

  const formatCost = (cost: number): string => {
    if (cost >= 1) return `$${cost.toFixed(2)}`;
    if (cost >= 0.01) return `$${cost.toFixed(3)}`;
    return `$${cost.toFixed(4)}`;
  };

  const formatTime = (ms: number): string => {
    if (ms >= 60000) return `${(ms / 60000).toFixed(1)}m`;
    if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
    return `${ms}ms`;
  };

  // Calculate token usage percentage
  const tokenPercent = status && status.maxTokens > 0
    ? Math.round((status.tokens / status.maxTokens) * 100)
    : null;

  // Determine token color based on usage
  const getTokenColor = (percent: number | null): string => {
    if (percent === null) return theme.colors.textMuted;
    if (percent >= 90) return theme.colors.error;
    if (percent >= 70) return theme.colors.warning;
    return theme.colors.success;
  };

  return (
    <Box
      borderStyle={theme.borderStyle}
      borderColor={theme.colors.primary}
      paddingX={1}
      justifyContent="space-between"
      width="100%"
    >
      {/* Left: Title and Model */}
      <Box>
        <Text bold color={theme.colors.primary}>
          {title}
        </Text>
        {status?.model && (
          <Text color={theme.colors.textMuted}>
            {' '}| {status.model}
          </Text>
        )}
      </Box>

      {/* Right: Metrics */}
      {showMetrics && status && (
        <Box gap={1}>
          {/* Iteration */}
          <Text color={theme.colors.textMuted}>
            iter:{status.iteration}
          </Text>

          {/* Tokens */}
          <Text color={getTokenColor(tokenPercent)}>
            tok:{formatTokens(status.tokens)}
            {tokenPercent !== null && `(${tokenPercent}%)`}
          </Text>

          {/* TODO: Cost display disabled - needs accurate pricing from OpenRouter generation endpoint */}

          {/* Time */}
          <Text color={theme.colors.textMuted}>
            {formatTime(status.elapsed)}
          </Text>
        </Box>
      )}
    </Box>
  );
}

export default Header;
