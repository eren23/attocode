/**
 * Sidebar Component
 *
 * Displays session list, navigation, and quick actions.
 */

import React, { useState } from 'react';
import { Box, Text, useInput } from 'ink';
import type { SessionDisplay } from '../types.js';
import type { Theme } from '../theme/index.js';

export interface SidebarProps {
  theme: Theme;
  sessions: SessionDisplay[];
  activeSessionId: string | null;
  onSessionSelect?: (sessionId: string) => void;
  onNewSession?: () => void;
  width?: number;
  focused?: boolean;
}

export function Sidebar({
  theme,
  sessions,
  activeSessionId,
  onSessionSelect,
  onNewSession,
  width = 30,
  focused = false,
}: SidebarProps) {
  const [selectedIndex, setSelectedIndex] = useState(0);

  // Handle keyboard navigation when focused
  useInput((input, key) => {
    if (!focused) return;

    if (key.upArrow) {
      setSelectedIndex(i => Math.max(0, i - 1));
    } else if (key.downArrow) {
      setSelectedIndex(i => Math.min(sessions.length - 1, i + 1));
    } else if (key.return) {
      if (selectedIndex < sessions.length) {
        onSessionSelect?.(sessions[selectedIndex].id);
      }
    } else if (input === 'n') {
      onNewSession?.();
    }
  }, { isActive: focused });

  const formatDate = (date: Date): string => {
    const now = new Date();
    const diff = now.getTime() - date.getTime();
    const hours = Math.floor(diff / (1000 * 60 * 60));
    const days = Math.floor(hours / 24);

    if (days > 0) return `${days}d ago`;
    if (hours > 0) return `${hours}h ago`;
    return 'now';
  };

  const formatTokens = (tokens: number): string => {
    if (tokens >= 1000) return `${(tokens / 1000).toFixed(1)}k`;
    return tokens.toString();
  };

  return (
    <Box
      flexDirection="column"
      width={width}
      borderStyle={theme.borderStyle}
      borderColor={focused ? theme.colors.borderFocus : theme.colors.border}
      paddingX={1}
    >
      {/* Header */}
      <Box justifyContent="space-between" marginBottom={1}>
        <Text bold color={theme.colors.primary}>Sessions</Text>
        <Text color={theme.colors.textMuted}>({sessions.length})</Text>
      </Box>

      {/* Session List */}
      <Box flexDirection="column" flexGrow={1}>
        {sessions.length === 0 ? (
          <Text color={theme.colors.textMuted}>No sessions</Text>
        ) : (
          sessions.map((session, index) => {
            const isActive = session.id === activeSessionId;
            const isSelected = focused && index === selectedIndex;

            return (
              <Box
                key={session.id}
                flexDirection="column"
                marginBottom={1}
                paddingX={isSelected ? 0 : 1}
              >
                <Box>
                  {/* Selection indicator */}
                  {isSelected && (
                    <Text color={theme.colors.primary}>{'>'} </Text>
                  )}
                  {/* Active indicator */}
                  {isActive && !isSelected && (
                    <Text color={theme.colors.success}>* </Text>
                  )}
                  {!isActive && !isSelected && (
                    <Text>  </Text>
                  )}

                  {/* Session name */}
                  <Text
                    color={isActive ? theme.colors.primary : theme.colors.text}
                    bold={isActive}
                  >
                    {session.name || session.id.slice(0, 8)}
                  </Text>
                </Box>

                {/* Session metadata */}
                <Box marginLeft={2}>
                  <Text color={theme.colors.textMuted} dimColor>
                    {session.messageCount} msgs | {formatTokens(session.tokenCount)} tok | {formatDate(session.lastActiveAt)}
                  </Text>
                </Box>
              </Box>
            );
          })
        )}
      </Box>

      {/* Footer with shortcuts */}
      <Box
        borderStyle="single"
        borderColor={theme.colors.border}
        borderTop={true}
        borderBottom={false}
        borderLeft={false}
        borderRight={false}
        paddingTop={1}
        marginTop={1}
      >
        <Text color={theme.colors.textMuted}>
          <Text color={theme.colors.accent}>n</Text>:new{' '}
          <Text color={theme.colors.accent}>Enter</Text>:select
        </Text>
      </Box>
    </Box>
  );
}

export default Sidebar;
