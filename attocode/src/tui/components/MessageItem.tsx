/**
 * MessageItem Component
 *
 * Memoized message renderer that prevents re-renders when parent state changes.
 * Uses Ink's Box and Text components for terminal rendering.
 */

import React, { memo } from 'react';
import { Box, Text } from 'ink';
import type { ThemeColors } from '../types.js';

/**
 * Message data structure for TUI display.
 */
export interface TUIMessage {
  id: string;
  role: 'user' | 'assistant' | 'error' | 'system';
  content: string;
  ts: Date;
}

export interface MessageItemProps {
  msg: TUIMessage;
  colors: ThemeColors;
}

/**
 * Memoized message item - prevents re-render when parent state changes.
 * Used within Ink's <Static> component for flicker-free rendering.
 */
export const MessageItem = memo(function MessageItem({ msg, colors }: MessageItemProps) {
  const isUser = msg.role === 'user';
  const isAssistant = msg.role === 'assistant';
  const isError = msg.role === 'error';
  const icon = isUser ? '>' : isAssistant ? '*' : isError ? 'x' : 'o';
  const roleColor = isUser ? '#87CEEB' : isAssistant ? '#98FB98' : isError ? '#FF6B6B' : '#FFD700';
  const label = isUser ? 'You' : isAssistant ? 'Assistant' : isError ? 'Error' : 'System';

  return React.createElement(Box, { marginBottom: 1, flexDirection: 'column' },
    // Role header
    React.createElement(Box, { gap: 1 },
      React.createElement(Text, { color: roleColor, bold: true }, icon),
      React.createElement(Text, { color: roleColor, bold: true }, label),
      React.createElement(Text, { color: colors.textMuted, dimColor: true },
        ` ${msg.ts.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })}`
      )
    ),
    // Message content
    React.createElement(Box, { marginLeft: 2 },
      React.createElement(Text, { wrap: 'wrap', color: isError ? colors.error : colors.text }, msg.content)
    )
  );
});

export default MessageItem;
