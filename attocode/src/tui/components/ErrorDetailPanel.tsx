/**
 * Error Detail Panel Component
 *
 * Displays expandable error information including stack traces.
 * Click/select an error to expand and see the full trace.
 *
 * Features:
 * - Collapsible stack traces
 * - Syntax highlighting for stack frames
 * - File path extraction with line numbers
 * - Copy path support
 */

import { memo, useState } from 'react';
import { Box, Text } from 'ink';
import type { ThemeColors } from '../types.js';

// =============================================================================
// TYPES
// =============================================================================

export interface ErrorDetail {
  id: string;
  message: string;
  stack?: string;
  code?: string;
  context?: string;
  timestamp: Date;
  recoverable?: boolean;
}

export interface ErrorDetailPanelProps {
  errors: ErrorDetail[];
  colors: ThemeColors;
  maxVisible?: number;
  expandedId?: string | null;
  onToggleExpand?: (id: string) => void;
}

export interface StackFrame {
  functionName: string;
  filePath: string;
  lineNumber: number;
  columnNumber?: number;
  isNative?: boolean;
  isNodeModules?: boolean;
}

// =============================================================================
// HELPERS
// =============================================================================

/**
 * Parse a stack trace string into structured stack frames.
 */
function parseStackTrace(stack: string): StackFrame[] {
  const frames: StackFrame[] = [];
  const lines = stack.split('\n');

  for (const line of lines) {
    // Match common stack trace formats
    // Node.js: "    at functionName (path:line:col)"
    // Node.js: "    at path:line:col"
    const nodeMatch = line.match(/^\s*at\s+(?:(.+?)\s+\()?(.+?):(\d+)(?::(\d+))?\)?$/);

    if (nodeMatch) {
      const [, functionName, filePath, lineNum, colNum] = nodeMatch;
      frames.push({
        functionName: functionName || '<anonymous>',
        filePath: filePath,
        lineNumber: parseInt(lineNum, 10),
        columnNumber: colNum ? parseInt(colNum, 10) : undefined,
        isNative: filePath.startsWith('native ') || filePath.startsWith('internal/'),
        isNodeModules: filePath.includes('node_modules'),
      });
    }
  }

  return frames;
}

/**
 * Format a file path for display (shorten if too long).
 */
function formatPath(path: string, maxLength: number = 60): string {
  if (path.length <= maxLength) return path;

  // Try to show the most relevant part (end of path)
  const parts = path.split('/');
  let result = parts.pop() || path;

  while (parts.length > 0 && result.length < maxLength - 10) {
    const nextPart = parts.pop();
    if (nextPart) {
      const newResult = `${nextPart}/${result}`;
      if (newResult.length > maxLength) break;
      result = newResult;
    }
  }

  return parts.length > 0 ? `.../${result}` : result;
}

/**
 * Format timestamp for display.
 */
function formatTimestamp(date: Date): string {
  return date.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

// =============================================================================
// STACK FRAME COMPONENT
// =============================================================================

interface StackFrameItemProps {
  frame: StackFrame;
  colors: ThemeColors;
  index: number;
}

const StackFrameItem = memo(function StackFrameItem({
  frame,
  colors,
  index,
}: StackFrameItemProps) {
  // Dim node_modules and native frames
  const isDimmed = frame.isNative || frame.isNodeModules;

  return (
    <Box marginLeft={4}>
      <Text color={colors.textMuted} dimColor>{`${index + 1}. `}</Text>
      <Text color={isDimmed ? colors.textMuted : '#87CEEB'} dimColor={isDimmed}>
        {frame.functionName}
      </Text>
      <Text color={colors.textMuted}> at </Text>
      <Text color={isDimmed ? colors.textMuted : '#98FB98'} dimColor={isDimmed}>
        {formatPath(frame.filePath)}:{frame.lineNumber}
        {frame.columnNumber ? `:${frame.columnNumber}` : ''}
      </Text>
    </Box>
  );
});

// =============================================================================
// ERROR ITEM COMPONENT
// =============================================================================

interface ErrorItemProps {
  error: ErrorDetail;
  colors: ThemeColors;
  expanded: boolean;
  onToggle: () => void;
}

const ErrorItem = memo(function ErrorItem({
  error,
  colors,
  expanded,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  onToggle: _onToggle, // Reserved for future click handler support in Ink
}: ErrorItemProps) {
  const frames = error.stack ? parseStackTrace(error.stack) : [];
  const hasStack = frames.length > 0;

  return (
    <Box flexDirection="column" marginBottom={1}>
      {/* Error header (clickable to expand) */}
      <Box gap={1}>
        <Text color={colors.error} bold>
          {expanded ? '[v]' : '[>]'}
        </Text>
        <Text color={colors.textMuted} dimColor>
          {formatTimestamp(error.timestamp)}
        </Text>
        {error.code && (
          <Text color="#FFD700">[{error.code}]</Text>
        )}
        <Text color={colors.error} wrap="truncate-end">
          {error.message.length > 80 && !expanded
            ? error.message.slice(0, 77) + '...'
            : error.message}
        </Text>
        {!error.recoverable && (
          <Text color={colors.error} dimColor>[fatal]</Text>
        )}
      </Box>

      {/* Expanded content */}
      {expanded && (
        <Box flexDirection="column" marginLeft={2}>
          {/* Context if available */}
          {error.context && (
            <Box marginBottom={1}>
              <Text color={colors.textMuted}>Context: </Text>
              <Text color={colors.text}>{error.context}</Text>
            </Box>
          )}

          {/* Stack trace */}
          {hasStack ? (
            <Box flexDirection="column">
              <Text color={colors.textMuted} dimColor>Stack trace ({frames.length} frames):</Text>
              {frames.slice(0, 10).map((frame, i) => (
                <StackFrameItem
                  key={`${error.id}-frame-${i}`}
                  frame={frame}
                  colors={colors}
                  index={i}
                />
              ))}
              {frames.length > 10 && (
                <Box marginLeft={4}>
                  <Text color={colors.textMuted} dimColor>
                    ... and {frames.length - 10} more frames
                  </Text>
                </Box>
              )}
            </Box>
          ) : error.stack ? (
            <Box flexDirection="column">
              <Text color={colors.textMuted} dimColor>Raw stack:</Text>
              <Box marginLeft={2}>
                <Text color={colors.textMuted} dimColor>
                  {error.stack.slice(0, 500)}
                  {error.stack.length > 500 ? '...' : ''}
                </Text>
              </Box>
            </Box>
          ) : null}
        </Box>
      )}
    </Box>
  );
});

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export const ErrorDetailPanel = memo(function ErrorDetailPanel({
  errors,
  colors,
  maxVisible = 5,
  expandedId,
  onToggleExpand,
}: ErrorDetailPanelProps) {
  // Internal expansion state if no external control provided
  const [internalExpanded, setInternalExpanded] = useState<string | null>(null);
  const actualExpanded = expandedId !== undefined ? expandedId : internalExpanded;
  const handleToggle = onToggleExpand || ((id: string) =>
    setInternalExpanded(prev => prev === id ? null : id)
  );

  if (errors.length === 0) {
    return null;
  }

  // Show only the most recent errors
  const visibleErrors = errors.slice(-maxVisible);

  return (
    <Box
      flexDirection="column"
      marginBottom={1}
      borderStyle="single"
      borderColor={colors.error}
      paddingX={1}
    >
      <Box justifyContent="space-between">
        <Text color={colors.error} bold>[!] Errors ({errors.length})</Text>
        <Text color={colors.textMuted} dimColor>
          Click to expand stack trace
        </Text>
      </Box>
      <Box flexDirection="column" marginTop={1}>
        {visibleErrors.map(error => (
          <ErrorItem
            key={error.id}
            error={error}
            colors={colors}
            expanded={actualExpanded === error.id}
            onToggle={() => handleToggle(error.id)}
          />
        ))}
        {errors.length > maxVisible && (
          <Text color={colors.textMuted} dimColor>
            ... and {errors.length - maxVisible} older errors
          </Text>
        )}
      </Box>
    </Box>
  );
});

// =============================================================================
// UTILITY EXPORTS
// =============================================================================

export { parseStackTrace, formatPath };
export default ErrorDetailPanel;
