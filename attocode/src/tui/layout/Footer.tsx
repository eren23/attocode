/**
 * Footer Component
 *
 * Displays mode indicator, keyboard shortcuts, and status messages.
 */

import React from 'react';
import { Box, Text } from 'ink';
import type { Theme } from '../theme/index.js';

export interface FooterProps {
  theme: Theme;
  mode?: string;
  message?: string;
  showShortcuts?: boolean;
  /** Current state of tool calls expansion (for Cmd+T indicator) */
  toolCallsExpanded?: boolean;
  /** Current state of thinking panel visibility (for Cmd+O indicator) */
  showThinkingPanel?: boolean;
}

// Standard keyboard shortcuts (static ones)
const baseShortcuts = [
  { key: 'Ctrl+P', action: 'Commands' },
  { key: 'Ctrl+L', action: 'Clear' },
  { key: 'Ctrl+C', action: 'Exit' },
];

export function Footer({
  theme,
  mode = 'ready',
  message,
  showShortcuts = true,
  toolCallsExpanded,
  showThinkingPanel,
}: FooterProps) {
  // Build dynamic shortcuts based on current state
  const shortcuts = [
    ...baseShortcuts,
    { key: 'Cmd+T', action: toolCallsExpanded ? 'Tools[-]' : 'Tools[+]' },
    { key: 'Cmd+O', action: showThinkingPanel ? 'Think[ON]' : 'Think[OFF]' },
  ];
  // Mode indicator colors
  const getModeColor = (m: string): string => {
    switch (m.toLowerCase()) {
      case 'running':
      case 'executing':
        return theme.colors.info;
      case 'waiting':
      case 'ready':
        return theme.colors.success;
      case 'error':
      case 'failed':
        return theme.colors.error;
      case 'paused':
        return theme.colors.warning;
      default:
        return theme.colors.textMuted;
    }
  };

  return (
    <Box
      paddingX={1}
      justifyContent="space-between"
      width="100%"
      borderStyle="single"
      borderColor={theme.colors.border}
      borderTop={true}
      borderBottom={false}
      borderLeft={false}
      borderRight={false}
    >
      {/* Left: Mode and Message */}
      <Box gap={1}>
        <Text color={getModeColor(mode)}>
          [{mode}]
        </Text>
        {message && (
          <Text color={theme.colors.text}>
            {message}
          </Text>
        )}
      </Box>

      {/* Right: Keyboard Shortcuts */}
      {showShortcuts && (
        <Box gap={1}>
          {shortcuts.map((s, i) => (
            <React.Fragment key={s.key}>
              {i > 0 && <Text color={theme.colors.textMuted}>|</Text>}
              <Text>
                <Text color={theme.colors.accent}>{s.key}</Text>
                <Text color={theme.colors.textMuted}>:{s.action}</Text>
              </Text>
            </React.Fragment>
          ))}
        </Box>
      )}
    </Box>
  );
}

export default Footer;
