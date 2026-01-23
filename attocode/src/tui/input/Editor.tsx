/**
 * Editor Component
 *
 * Text input editor with multi-line support and keyboard handling.
 */

import React, { useState, useCallback } from 'react';
import { Box, Text, useInput } from 'ink';
import type { Theme } from '../theme/index.js';

export interface EditorProps {
  theme: Theme;
  value: string;
  onChange: (value: string) => void;
  onSubmit: (value: string) => void;
  onCancel?: () => void;
  placeholder?: string;
  multiline?: boolean;
  disabled?: boolean;
  focused?: boolean;
  prompt?: string;
  maxHeight?: number;
}

/**
 * Calculate cursor position in multi-line text.
 */
function getCursorPosition(text: string, cursorIndex: number): { line: number; column: number } {
  const lines = text.slice(0, cursorIndex).split('\n');
  return {
    line: lines.length - 1,
    column: lines[lines.length - 1].length,
  };
}

/**
 * Text input editor component.
 */
export function Editor({
  theme,
  value,
  onChange,
  onSubmit,
  onCancel,
  placeholder = 'Type a message...',
  multiline = false,
  disabled = false,
  focused = true,
  prompt = '>',
  maxHeight = 10,
}: EditorProps) {
  const [cursorPosition, setCursorPosition] = useState(value.length);
  const [historyIndex, setHistoryIndex] = useState(-1);

  // Handle keyboard input
  useInput((input, key) => {
    if (!focused || disabled) return;

    // Submit on Enter (Shift+Enter for newline in multiline mode)
    if (key.return) {
      if (multiline && key.shift) {
        // Insert newline
        const newValue = value.slice(0, cursorPosition) + '\n' + value.slice(cursorPosition);
        onChange(newValue);
        setCursorPosition(cursorPosition + 1);
      } else if (value.trim()) {
        onSubmit(value);
        setCursorPosition(0);
      }
      return;
    }

    // Cancel on Escape
    if (key.escape) {
      onCancel?.();
      return;
    }

    // Backspace
    if (key.backspace || key.delete) {
      if (cursorPosition > 0) {
        const newValue = value.slice(0, cursorPosition - 1) + value.slice(cursorPosition);
        onChange(newValue);
        setCursorPosition(cursorPosition - 1);
      }
      return;
    }

    // Arrow keys for cursor movement
    if (key.leftArrow) {
      setCursorPosition(Math.max(0, cursorPosition - 1));
      return;
    }
    if (key.rightArrow) {
      setCursorPosition(Math.min(value.length, cursorPosition + 1));
      return;
    }

    // Home/End
    if (key.ctrl && input === 'a') {
      setCursorPosition(0);
      return;
    }
    if (key.ctrl && input === 'e') {
      setCursorPosition(value.length);
      return;
    }

    // Clear line
    if (key.ctrl && input === 'u') {
      onChange('');
      setCursorPosition(0);
      return;
    }

    // Delete word
    if (key.ctrl && input === 'w') {
      const beforeCursor = value.slice(0, cursorPosition);
      const lastSpace = beforeCursor.lastIndexOf(' ');
      const newValue = value.slice(0, lastSpace + 1) + value.slice(cursorPosition);
      onChange(newValue);
      setCursorPosition(lastSpace + 1);
      return;
    }

    // Regular character input
    if (input && !key.ctrl && !key.meta) {
      const newValue = value.slice(0, cursorPosition) + input + value.slice(cursorPosition);
      onChange(newValue);
      setCursorPosition(cursorPosition + input.length);
    }
  }, { isActive: focused });

  // Split value into lines for multi-line display
  const lines = value.split('\n');
  const { line: cursorLine, column: cursorColumn } = getCursorPosition(value, cursorPosition);

  // Limit visible lines
  const visibleLines = lines.slice(0, maxHeight);
  const hasMore = lines.length > maxHeight;

  return (
    <Box
      flexDirection="column"
      borderStyle={theme.borderStyle}
      borderColor={focused && !disabled ? theme.colors.borderFocus : theme.colors.border}
      paddingX={1}
    >
      {/* Multi-line indicator */}
      {multiline && lines.length > 1 && (
        <Box justifyContent="flex-end">
          <Text color={theme.colors.textMuted}>
            line {cursorLine + 1}/{lines.length}
          </Text>
        </Box>
      )}

      {/* Input area */}
      <Box flexDirection="row">
        {/* Prompt */}
        <Text color={disabled ? theme.colors.textMuted : theme.colors.primary}>
          {prompt}{' '}
        </Text>

        {/* Content or placeholder */}
        {value.length === 0 && !focused ? (
          <Text color={theme.colors.textMuted}>{placeholder}</Text>
        ) : (
          <Box flexDirection="column">
            {visibleLines.map((line, lineIndex) => (
              <Box key={lineIndex}>
                {lineIndex === cursorLine ? (
                  // Line with cursor
                  <>
                    <Text>{line.slice(0, cursorColumn)}</Text>
                    {focused && !disabled && (
                      <Text backgroundColor={theme.colors.primary} color={theme.colors.textInverse}>
                        {line[cursorColumn] || ' '}
                      </Text>
                    )}
                    <Text>{line.slice(cursorColumn + 1)}</Text>
                  </>
                ) : (
                  <Text>{line}</Text>
                )}
              </Box>
            ))}
          </Box>
        )}
      </Box>

      {/* Truncation indicator */}
      {hasMore && (
        <Text color={theme.colors.textMuted}>
          ... {lines.length - visibleLines.length} more lines
        </Text>
      )}

      {/* Hint for multi-line */}
      {multiline && focused && (
        <Box marginTop={1}>
          <Text color={theme.colors.textMuted}>
            Shift+Enter for newline | Enter to submit | Esc to cancel
          </Text>
        </Box>
      )}
    </Box>
  );
}

export default Editor;
