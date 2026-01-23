/**
 * MessageList Component
 *
 * Displays conversation messages with role-based styling and markdown rendering.
 */

import React, { useMemo } from 'react';
import { Box, Text } from 'ink';
import type { MessageDisplay } from '../types.js';
import type { Theme } from '../theme/index.js';
import { CodeBlock } from './CodeBlock.js';

export interface MessageListProps {
  theme: Theme;
  messages: MessageDisplay[];
  maxHeight?: number;
  showTimestamps?: boolean;
  showRoleIcons?: boolean;
  onMessageClick?: (id: string) => void;
}

interface MessageItemProps {
  theme: Theme;
  message: MessageDisplay;
  showTimestamp?: boolean;
  showRoleIcon?: boolean;
}

// Role configuration
const roleConfig: Record<string, { icon: string; label: string }> = {
  user: { icon: 'You', label: 'You' },
  assistant: { icon: 'AI', label: 'Assistant' },
  system: { icon: 'Sys', label: 'System' },
  tool: { icon: 'Tool', label: 'Tool' },
};

/**
 * Parse message content to extract code blocks and regular text.
 */
function parseContent(content: string): Array<{ type: 'text' | 'code'; content: string; language?: string }> {
  const parts: Array<{ type: 'text' | 'code'; content: string; language?: string }> = [];
  const codeBlockRegex = /```(\w*)\n([\s\S]*?)```/g;

  let lastIndex = 0;
  let match;

  // Use matchAll instead of exec loop
  const matches = Array.from(content.matchAll(codeBlockRegex));

  for (const match of matches) {
    // Add text before code block
    if (match.index !== undefined && match.index > lastIndex) {
      const text = content.slice(lastIndex, match.index).trim();
      if (text) {
        parts.push({ type: 'text', content: text });
      }
    }

    // Add code block
    parts.push({
      type: 'code',
      content: match[2].trim(),
      language: match[1] || undefined,
    });

    lastIndex = (match.index ?? 0) + match[0].length;
  }

  // Add remaining text
  if (lastIndex < content.length) {
    const text = content.slice(lastIndex).trim();
    if (text) {
      parts.push({ type: 'text', content: text });
    }
  }

  // If no parts found, treat entire content as text
  if (parts.length === 0 && content.trim()) {
    parts.push({ type: 'text', content: content.trim() });
  }

  return parts;
}

/**
 * Format timestamp for display.
 */
function formatTimestamp(date: Date): string {
  const hours = date.getHours().toString().padStart(2, '0');
  const minutes = date.getMinutes().toString().padStart(2, '0');
  return `${hours}:${minutes}`;
}

/**
 * Single message item component.
 */
function MessageItem({
  theme,
  message,
  showTimestamp = false,
  showRoleIcon = true,
}: MessageItemProps) {
  const config = roleConfig[message.role] || { icon: '?', label: message.role };

  // Get role-specific color
  const roleColors: Record<string, string> = {
    user: theme.colors.userMessage,
    assistant: theme.colors.assistantMessage,
    system: theme.colors.systemMessage,
    tool: theme.colors.toolMessage,
  };
  const roleColor = roleColors[message.role] || theme.colors.text;

  // Parse content for code blocks
  const contentParts = useMemo(() => parseContent(message.content), [message.content]);

  return (
    <Box flexDirection="column" marginBottom={1}>
      {/* Header: Role and timestamp */}
      <Box gap={1}>
        {showRoleIcon && (
          <Text bold color={roleColor}>
            [{config.icon}]
          </Text>
        )}
        {showTimestamp && message.timestamp && (
          <Text color={theme.colors.textMuted}>
            {formatTimestamp(message.timestamp)}
          </Text>
        )}
        {message.streaming && (
          <Text color={theme.colors.info}>...</Text>
        )}
      </Box>

      {/* Content */}
      <Box flexDirection="column" marginLeft={showRoleIcon ? 2 : 0}>
        {contentParts.map((part, index) => (
          part.type === 'code' ? (
            <CodeBlock
              key={index}
              theme={theme}
              code={part.content}
              language={part.language}
              showLineNumbers={part.content.split('\n').length > 3}
            />
          ) : (
            <Text key={index} wrap="wrap">
              {part.content}
            </Text>
          )
        ))}
      </Box>
    </Box>
  );
}

/**
 * Message list component displaying conversation history.
 */
export function MessageList({
  theme,
  messages,
  maxHeight = 20,
  showTimestamps = false,
  showRoleIcons = true,
}: MessageListProps) {
  // Calculate visible messages based on maxHeight
  // Rough estimate: each message takes ~3 lines average
  const estimatedMessagesPerScreen = Math.floor(maxHeight / 3);
  const visibleMessages = messages.slice(-estimatedMessagesPerScreen);

  const hasMore = messages.length > visibleMessages.length;

  return (
    <Box flexDirection="column" flexGrow={1}>
      {/* Scroll indicator */}
      {hasMore && (
        <Box justifyContent="center" marginBottom={1}>
          <Text color={theme.colors.textMuted}>
            --- {messages.length - visibleMessages.length} more messages above ---
          </Text>
        </Box>
      )}

      {/* Empty state */}
      {messages.length === 0 && (
        <Box justifyContent="center" alignItems="center" flexGrow={1}>
          <Text color={theme.colors.textMuted}>
            No messages yet. Type a message to start.
          </Text>
        </Box>
      )}

      {/* Messages */}
      {visibleMessages.map((msg) => (
        <MessageItem
          key={msg.id}
          theme={theme}
          message={msg}
          showTimestamp={showTimestamps}
          showRoleIcon={showRoleIcons}
        />
      ))}
    </Box>
  );
}

export default MessageList;
