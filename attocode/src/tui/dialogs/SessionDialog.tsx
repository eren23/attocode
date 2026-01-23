/**
 * Session Dialog Component
 *
 * Dialog for session management operations.
 */

import React, { useState } from 'react';
import { Box, Text, useInput } from 'ink';
import type { SessionDisplay } from '../types.js';
import type { Theme } from '../theme/index.js';
import { BaseDialog } from './Dialog.js';

export interface SessionDialogProps {
  theme: Theme;
  sessions: SessionDisplay[];
  currentSessionId: string | null;
  onSelect: (sessionId: string) => void;
  onNew: () => void;
  onDelete: (sessionId: string) => void;
  onRename: (sessionId: string, newName: string) => void;
  onFork: (sessionId: string) => void;
  onExport: (sessionId: string) => void;
  onClose: () => void;
}

type DialogMode = 'list' | 'rename' | 'confirm-delete';

/**
 * Format date for display.
 */
function formatDate(date: Date): string {
  const now = new Date();
  const diff = now.getTime() - date.getTime();
  const minutes = Math.floor(diff / (1000 * 60));
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);

  if (days > 0) return `${days}d ago`;
  if (hours > 0) return `${hours}h ago`;
  if (minutes > 0) return `${minutes}m ago`;
  return 'just now';
}

/**
 * Format token count.
 */
function formatTokens(tokens: number): string {
  if (tokens >= 1000000) return `${(tokens / 1000000).toFixed(1)}M`;
  if (tokens >= 1000) return `${(tokens / 1000).toFixed(1)}k`;
  return tokens.toString();
}

/**
 * Session dialog for managing sessions.
 */
export function SessionDialog({
  theme,
  sessions,
  currentSessionId,
  onSelect,
  onNew,
  onDelete,
  onRename,
  onFork,
  onExport,
  onClose,
}: SessionDialogProps) {
  const [selectedIndex, setSelectedIndex] = useState(
    Math.max(0, sessions.findIndex(s => s.id === currentSessionId))
  );
  const [mode, setMode] = useState<DialogMode>('list');
  const [renameValue, setRenameValue] = useState('');

  const selectedSession = sessions[selectedIndex];

  useInput((input, key) => {
    // Handle rename mode
    if (mode === 'rename') {
      if (key.return) {
        if (renameValue.trim()) {
          onRename(selectedSession.id, renameValue.trim());
        }
        setMode('list');
        setRenameValue('');
      } else if (key.escape) {
        setMode('list');
        setRenameValue('');
      } else if (key.backspace || key.delete) {
        setRenameValue(v => v.slice(0, -1));
      } else if (input && !key.ctrl && !key.meta) {
        setRenameValue(v => v + input);
      }
      return;
    }

    // Handle confirm delete mode
    if (mode === 'confirm-delete') {
      if (input === 'y' || input === 'Y') {
        onDelete(selectedSession.id);
        setMode('list');
        setSelectedIndex(Math.max(0, selectedIndex - 1));
      } else if (input === 'n' || input === 'N' || key.escape) {
        setMode('list');
      }
      return;
    }

    // List mode navigation
    if (key.upArrow) {
      setSelectedIndex(i => Math.max(0, i - 1));
    } else if (key.downArrow) {
      setSelectedIndex(i => Math.min(sessions.length - 1, i + 1));
    } else if (key.return) {
      if (selectedSession) {
        onSelect(selectedSession.id);
        onClose();
      }
    } else if (key.escape) {
      onClose();
    } else if (input === 'n' || input === 'N') {
      onNew();
    } else if (input === 'r' || input === 'R') {
      if (selectedSession) {
        setRenameValue(selectedSession.name || '');
        setMode('rename');
      }
    } else if (input === 'd' || input === 'D') {
      if (selectedSession && selectedSession.id !== currentSessionId) {
        setMode('confirm-delete');
      }
    } else if (input === 'f' || input === 'F') {
      if (selectedSession) {
        onFork(selectedSession.id);
      }
    } else if (input === 'e' || input === 'E') {
      if (selectedSession) {
        onExport(selectedSession.id);
      }
    }
  });

  // Rename mode UI
  if (mode === 'rename') {
    return (
      <BaseDialog theme={theme} title="Rename Session" width={50}>
        <Box marginBottom={1}>
          <Text>Enter new name for session:</Text>
        </Box>

        <Box
          borderStyle="single"
          borderColor={theme.colors.borderFocus}
          paddingX={1}
        >
          <Text color={theme.colors.primary}>{'>'} </Text>
          {renameValue ? (
            <Text>{renameValue}</Text>
          ) : (
            <Text color={theme.colors.textMuted}>Session name...</Text>
          )}
          <Text backgroundColor={theme.colors.primary} color={theme.colors.textInverse}>
            {' '}
          </Text>
        </Box>

        <Box marginTop={2} justifyContent="center">
          <Text color={theme.colors.textMuted}>
            <Text color={theme.colors.accent}>Enter</Text> to save | <Text color={theme.colors.accent}>Esc</Text> to cancel
          </Text>
        </Box>
      </BaseDialog>
    );
  }

  // Confirm delete mode UI
  if (mode === 'confirm-delete') {
    return (
      <BaseDialog theme={theme} title="Delete Session" width={50}>
        <Box marginBottom={1}>
          <Text color={theme.colors.error}>
            Are you sure you want to delete this session?
          </Text>
        </Box>

        <Box marginBottom={1}>
          <Text bold>{selectedSession?.name || selectedSession?.id.slice(0, 8)}</Text>
        </Box>

        <Box marginBottom={1}>
          <Text color={theme.colors.textMuted}>
            This action cannot be undone.
          </Text>
        </Box>

        <Box marginTop={2} justifyContent="center">
          <Text color={theme.colors.textMuted}>
            <Text color={theme.colors.error}>y</Text> to delete | <Text color={theme.colors.accent}>n</Text> to cancel
          </Text>
        </Box>
      </BaseDialog>
    );
  }

  // List mode UI
  return (
    <BaseDialog theme={theme} title="Sessions" width={60}>
      {/* Session list */}
      <Box flexDirection="column" marginBottom={1}>
        {sessions.length === 0 ? (
          <Text color={theme.colors.textMuted}>No sessions available</Text>
        ) : (
          sessions.map((session, index) => {
            const isSelected = index === selectedIndex;
            const isCurrent = session.id === currentSessionId;

            return (
              <Box key={session.id} flexDirection="column" marginBottom={1}>
                <Box>
                  {/* Selection indicator */}
                  <Text color={isSelected ? theme.colors.primary : theme.colors.textMuted}>
                    {isSelected ? '>' : ' '}{' '}
                  </Text>

                  {/* Current indicator */}
                  <Text color={theme.colors.success}>
                    {isCurrent ? '*' : ' '}{' '}
                  </Text>

                  {/* Session name */}
                  <Text
                    color={isSelected ? theme.colors.primary : theme.colors.text}
                    bold={isSelected || isCurrent}
                  >
                    {session.name || session.id.slice(0, 8)}
                  </Text>
                </Box>

                {/* Session details */}
                {isSelected && (
                  <Box marginLeft={4} flexDirection="column">
                    <Text color={theme.colors.textMuted}>
                      {session.messageCount} messages | {formatTokens(session.tokenCount)} tokens
                    </Text>
                    <Text color={theme.colors.textMuted}>
                      Created: {formatDate(session.createdAt)} | Last active: {formatDate(session.lastActiveAt)}
                    </Text>
                  </Box>
                )}
              </Box>
            );
          })
        )}
      </Box>

      {/* Actions */}
      <Box
        borderStyle="single"
        borderColor={theme.colors.border}
        borderTop={true}
        borderBottom={false}
        borderLeft={false}
        borderRight={false}
        paddingTop={1}
        marginTop={1}
        justifyContent="center"
        gap={2}
      >
        <Text color={theme.colors.accent}>n</Text>
        <Text color={theme.colors.textMuted}>new</Text>
        <Text color={theme.colors.textMuted}>|</Text>
        <Text color={theme.colors.accent}>r</Text>
        <Text color={theme.colors.textMuted}>rename</Text>
        <Text color={theme.colors.textMuted}>|</Text>
        <Text color={theme.colors.accent}>f</Text>
        <Text color={theme.colors.textMuted}>fork</Text>
        <Text color={theme.colors.textMuted}>|</Text>
        <Text color={theme.colors.accent}>d</Text>
        <Text color={theme.colors.textMuted}>delete</Text>
        <Text color={theme.colors.textMuted}>|</Text>
        <Text color={theme.colors.accent}>e</Text>
        <Text color={theme.colors.textMuted}>export</Text>
      </Box>

      <Box marginTop={1} justifyContent="center">
        <Text color={theme.colors.textMuted}>
          <Text color={theme.colors.accent}>↑↓</Text> navigate | <Text color={theme.colors.accent}>Enter</Text> switch | <Text color={theme.colors.accent}>Esc</Text> close
        </Text>
      </Box>
    </BaseDialog>
  );
}

export default SessionDialog;
