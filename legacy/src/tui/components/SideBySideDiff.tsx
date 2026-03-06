/**
 * SideBySideDiff Component
 *
 * Displays a diff in side-by-side format with old content on the left
 * and new content on the right. Uses line-level diffing to align content.
 *
 * Features:
 * - Automatic terminal width detection
 * - Line number gutters (optional)
 * - Word-level highlighting within changed lines
 * - Truncation of long lines with ellipsis
 *
 * @example
 * ```tsx
 * <SideBySideDiff
 *   oldContent="const x = 1;"
 *   newContent="const x = 2;"
 *   oldPath="file.ts (before)"
 *   newPath="file.ts (after)"
 * />
 * ```
 */

import React, { memo, useMemo } from 'react';
import { Box, Text, useStdout } from 'ink';
import { diffLines, diffWords } from 'diff';
import type { ThemeColors } from '../types.js';
import { tokenize, detectLanguage, getTokenColor, type Token } from '../syntax/index.js';

// =============================================================================
// TYPES
// =============================================================================

interface SideBySideDiffProps {
  /** Content before changes */
  oldContent: string;
  /** Content after changes */
  newContent: string;
  /** Path/label for old content */
  oldPath?: string;
  /** Path/label for new content */
  newPath?: string;
  /** Show line numbers */
  showLineNumbers?: boolean;
  /** Maximum lines to show (default: 100) */
  maxLines?: number;
  /** Enable word-level diff within changed lines */
  showWordDiff?: boolean;
  /** Enable syntax highlighting for code */
  syntaxHighlight?: boolean;
  /** Theme colors for syntax highlighting */
  theme?: ThemeColors;
  /** File path for language detection */
  filePath?: string;
}

interface AlignedPair {
  /** Line content from old file (undefined if line was added) */
  old?: string;
  /** Line content from new file (undefined if line was removed) */
  new?: string;
  /** Type of change */
  type: 'unchanged' | 'add' | 'remove' | 'modify';
  /** Old line number (if applicable) */
  oldLineNum?: number;
  /** New line number (if applicable) */
  newLineNum?: number;
}

// =============================================================================
// COLORS
// =============================================================================

const COLORS = {
  addition: '#98FB98',
  additionBg: '#1a3d1a',
  deletion: '#FF6B6B',
  deletionBg: '#3d1a1a',
  unchanged: '#888888',
  border: '#444444',
  lineNumber: '#555555',
  header: '#87CEEB',
};

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

/**
 * Align old and new content lines for side-by-side display.
 */
function alignLines(oldContent: string, newContent: string): AlignedPair[] {
  const changes = diffLines(oldContent, newContent);
  const pairs: AlignedPair[] = [];

  let oldLineNum = 1;
  let newLineNum = 1;

  // Process changes and align them
  let i = 0;
  while (i < changes.length) {
    const change = changes[i];
    const lines = change.value.split('\n').filter(
      (l, idx, arr) =>
        // Keep all lines except trailing empty from split
        idx < arr.length - 1 || l !== '',
    );

    if (!change.added && !change.removed) {
      // Unchanged lines - show on both sides
      for (const line of lines) {
        pairs.push({
          old: line,
          new: line,
          type: 'unchanged',
          oldLineNum: oldLineNum++,
          newLineNum: newLineNum++,
        });
      }
    } else if (change.removed) {
      // Check if next change is an add (modification)
      const nextChange = changes[i + 1];
      if (nextChange?.added) {
        // This is a modification - pair up removed and added lines
        const removedLines = lines;
        const addedLines = nextChange.value
          .split('\n')
          .filter((l, idx, arr) => idx < arr.length - 1 || l !== '');

        const maxLen = Math.max(removedLines.length, addedLines.length);
        for (let j = 0; j < maxLen; j++) {
          const oldLine = removedLines[j];
          const newLine = addedLines[j];

          if (oldLine !== undefined && newLine !== undefined) {
            pairs.push({
              old: oldLine,
              new: newLine,
              type: 'modify',
              oldLineNum: oldLineNum++,
              newLineNum: newLineNum++,
            });
          } else if (oldLine !== undefined) {
            pairs.push({
              old: oldLine,
              new: undefined,
              type: 'remove',
              oldLineNum: oldLineNum++,
            });
          } else {
            pairs.push({
              old: undefined,
              new: newLine,
              type: 'add',
              newLineNum: newLineNum++,
            });
          }
        }
        i++; // Skip the next change since we processed it
      } else {
        // Pure removal
        for (const line of lines) {
          pairs.push({
            old: line,
            new: undefined,
            type: 'remove',
            oldLineNum: oldLineNum++,
          });
        }
      }
    } else if (change.added) {
      // Pure addition (no preceding removal)
      for (const line of lines) {
        pairs.push({
          old: undefined,
          new: line,
          type: 'add',
          newLineNum: newLineNum++,
        });
      }
    }

    i++;
  }

  return pairs;
}

/**
 * Truncate a string to fit width, adding ellipsis if needed.
 */
function truncate(str: string, maxWidth: number): string {
  if (str.length <= maxWidth) return str;
  return str.slice(0, maxWidth - 1) + '…';
}

/**
 * Render word-level diff highlighting for a modified line.
 */
function renderWordDiff(
  oldLine: string,
  newLine: string,
  side: 'old' | 'new',
  maxWidth: number,
): React.ReactNode {
  const changes = diffWords(oldLine, newLine);
  const elements: React.ReactNode[] = [];
  let currentWidth = 0;

  for (let i = 0; i < changes.length && currentWidth < maxWidth; i++) {
    const change = changes[i];
    let text = change.value;

    // Skip parts that don't belong on this side
    if (side === 'old' && change.added) continue;
    if (side === 'new' && change.removed) continue;

    // Truncate if needed
    const remaining = maxWidth - currentWidth;
    if (text.length > remaining) {
      text = text.slice(0, remaining - 1) + '…';
    }
    currentWidth += text.length;

    // Determine styling
    const isHighlighted = (side === 'old' && change.removed) || (side === 'new' && change.added);

    elements.push(
      <Text
        key={i}
        color={side === 'old' ? COLORS.deletion : COLORS.addition}
        bold={isHighlighted}
        inverse={isHighlighted}
      >
        {text}
      </Text>,
    );
  }

  return <>{elements}</>;
}

/**
 * Render word-level diff with syntax highlighting.
 */
function renderWordDiffWithSyntax(
  oldLine: string,
  newLine: string,
  side: 'old' | 'new',
  maxWidth: number,
  theme: ThemeColors,
  language: string,
): React.ReactNode {
  const changes = diffWords(oldLine, newLine);
  const elements: React.ReactNode[] = [];
  let currentWidth = 0;
  let keyIndex = 0;

  for (const change of changes) {
    if (currentWidth >= maxWidth) break;

    // Skip parts that don't belong on this side
    if (side === 'old' && change.added) continue;
    if (side === 'new' && change.removed) continue;

    let text = change.value;

    // Truncate if needed
    const remaining = maxWidth - currentWidth;
    if (text.length > remaining) {
      text = text.slice(0, remaining - 1) + '…';
    }
    currentWidth += text.length;

    // Determine if this part is highlighted (changed)
    const isHighlighted = (side === 'old' && change.removed) || (side === 'new' && change.added);

    if (isHighlighted) {
      // Changed parts get inverse highlighting
      elements.push(
        <Text
          key={keyIndex++}
          color={side === 'old' ? COLORS.deletion : COLORS.addition}
          bold
          inverse
        >
          {text}
        </Text>,
      );
    } else {
      // Unchanged parts get syntax highlighting
      const tokens = tokenize(text, language);
      for (const token of tokens) {
        elements.push(
          <Text key={keyIndex++} color={getTokenColor(token.type, theme)}>
            {token.content}
          </Text>,
        );
      }
    }
  }

  return <>{elements}</>;
}

/**
 * Render content with syntax highlighting.
 */
function renderSyntaxHighlight(
  content: string,
  maxWidth: number,
  theme: ThemeColors,
  language: string,
  _baseColor?: string,
): React.ReactNode {
  const truncated = content.length > maxWidth ? content.slice(0, maxWidth - 1) + '…' : content;

  const tokens = tokenize(truncated, language);
  return tokens.map((token: Token, i: number) => (
    <Text key={i} color={getTokenColor(token.type, theme)}>
      {token.content}
    </Text>
  ));
}

// =============================================================================
// SUB-COMPONENTS
// =============================================================================

/**
 * Render a single row of the side-by-side diff.
 */
const DiffRow = memo(function DiffRow({
  pair,
  halfWidth,
  showLineNumbers,
  lineNumWidth,
  showWordDiff,
  syntaxHighlight,
  theme,
  language,
}: {
  pair: AlignedPair;
  halfWidth: number;
  showLineNumbers: boolean;
  lineNumWidth: number;
  showWordDiff: boolean;
  syntaxHighlight?: boolean;
  theme?: ThemeColors;
  language?: string | null;
}) {
  const contentWidth = showLineNumbers ? halfWidth - lineNumWidth - 1 : halfWidth;

  // Determine colors based on change type
  const oldColor =
    pair.type === 'remove' || pair.type === 'modify' ? COLORS.deletion : COLORS.unchanged;
  const newColor =
    pair.type === 'add' || pair.type === 'modify' ? COLORS.addition : COLORS.unchanged;

  const oldBg = pair.type === 'remove' ? COLORS.deletionBg : undefined;
  const newBg = pair.type === 'add' ? COLORS.additionBg : undefined;

  // Check if we should use syntax highlighting
  const useSyntax = syntaxHighlight && theme && language;

  // Render content
  let oldContent: React.ReactNode;
  let newContent: React.ReactNode;

  if (showWordDiff && pair.type === 'modify' && pair.old && pair.new) {
    // Word diff with or without syntax
    if (useSyntax) {
      oldContent = renderWordDiffWithSyntax(
        pair.old,
        pair.new,
        'old',
        contentWidth,
        theme,
        language,
      );
      newContent = renderWordDiffWithSyntax(
        pair.old,
        pair.new,
        'new',
        contentWidth,
        theme,
        language,
      );
    } else {
      oldContent = renderWordDiff(pair.old, pair.new, 'old', contentWidth);
      newContent = renderWordDiff(pair.old, pair.new, 'new', contentWidth);
    }
  } else if (useSyntax) {
    // Syntax highlighting without word diff
    oldContent =
      pair.old !== undefined
        ? renderSyntaxHighlight(pair.old, contentWidth, theme, language, oldColor)
        : null;
    newContent =
      pair.new !== undefined
        ? renderSyntaxHighlight(pair.new, contentWidth, theme, language, newColor)
        : null;
  } else {
    // Plain text
    oldContent =
      pair.old !== undefined ? (
        <Text color={oldColor}>{truncate(pair.old, contentWidth)}</Text>
      ) : null;
    newContent =
      pair.new !== undefined ? (
        <Text color={newColor}>{truncate(pair.new, contentWidth)}</Text>
      ) : null;
  }

  return (
    <Box>
      {/* Old side */}
      <Box width={halfWidth}>
        {showLineNumbers && (
          <Text color={COLORS.lineNumber} dimColor>
            {(pair.oldLineNum?.toString() || '').padStart(lineNumWidth)}
          </Text>
        )}
        {showLineNumbers && <Text> </Text>}
        <Box width={contentWidth}>
          <Text backgroundColor={oldBg}>{oldContent || ' '}</Text>
        </Box>
      </Box>

      {/* Separator */}
      <Text color={COLORS.border}>│</Text>

      {/* New side */}
      <Box width={halfWidth}>
        {showLineNumbers && (
          <Text color={COLORS.lineNumber} dimColor>
            {(pair.newLineNum?.toString() || '').padStart(lineNumWidth)}
          </Text>
        )}
        {showLineNumbers && <Text> </Text>}
        <Box width={contentWidth}>
          <Text backgroundColor={newBg}>{newContent || ' '}</Text>
        </Box>
      </Box>
    </Box>
  );
});

/**
 * Render the header row showing file paths.
 */
const DiffHeader = memo(function DiffHeader({
  oldPath,
  newPath,
  halfWidth,
}: {
  oldPath: string;
  newPath: string;
  halfWidth: number;
}) {
  return (
    <Box borderStyle="single" borderColor={COLORS.border}>
      <Box width={halfWidth}>
        <Text color={COLORS.deletion} bold>
          {truncate(oldPath || 'Old', halfWidth - 2)}
        </Text>
      </Box>
      <Text color={COLORS.border}>│</Text>
      <Box width={halfWidth}>
        <Text color={COLORS.addition} bold>
          {truncate(newPath || 'New', halfWidth - 2)}
        </Text>
      </Box>
    </Box>
  );
});

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export const SideBySideDiff = memo(function SideBySideDiff({
  oldContent,
  newContent,
  oldPath,
  newPath,
  showLineNumbers = true,
  maxLines = 100,
  showWordDiff = true,
  syntaxHighlight = false,
  theme,
  filePath,
}: SideBySideDiffProps) {
  const { stdout } = useStdout();
  const termWidth = stdout?.columns || 80;

  // Calculate widths
  const halfWidth = Math.floor((termWidth - 1) / 2); // -1 for separator
  const lineNumWidth = 4;

  // Detect language for syntax highlighting
  const detectedLanguage = useMemo(() => {
    if (!syntaxHighlight) return null;
    // Try filePath first
    if (filePath) {
      return detectLanguage(filePath);
    }
    // Fall back to newPath/oldPath
    const path = newPath || oldPath;
    if (path) return detectLanguage(path);
    return null;
  }, [syntaxHighlight, filePath, newPath, oldPath]);

  // Align lines
  const alignedPairs = useMemo(() => alignLines(oldContent, newContent), [oldContent, newContent]);

  // Apply max lines limit
  const displayPairs = alignedPairs.slice(0, maxLines);
  const hasMore = alignedPairs.length > maxLines;

  // Calculate stats
  const stats = useMemo(() => {
    let additions = 0;
    let deletions = 0;
    let modifications = 0;

    for (const pair of alignedPairs) {
      if (pair.type === 'add') additions++;
      else if (pair.type === 'remove') deletions++;
      else if (pair.type === 'modify') modifications++;
    }

    return { additions, deletions, modifications };
  }, [alignedPairs]);

  return (
    <Box flexDirection="column">
      {/* Header with file names */}
      <DiffHeader
        oldPath={oldPath || 'Original'}
        newPath={newPath || 'Modified'}
        halfWidth={halfWidth}
      />

      {/* Stats summary */}
      <Box marginBottom={1}>
        <Text color={COLORS.addition}>+{stats.additions} </Text>
        <Text color={COLORS.deletion}>-{stats.deletions} </Text>
        <Text color={COLORS.header}>~{stats.modifications}</Text>
      </Box>

      {/* Diff rows */}
      {displayPairs.map((pair, i) => (
        <DiffRow
          key={i}
          pair={pair}
          halfWidth={halfWidth}
          showLineNumbers={showLineNumbers}
          lineNumWidth={lineNumWidth}
          showWordDiff={showWordDiff}
          syntaxHighlight={syntaxHighlight}
          theme={theme}
          language={detectedLanguage}
        />
      ))}

      {/* Truncation notice */}
      {hasMore && (
        <Text color={COLORS.unchanged} dimColor>
          ... ({alignedPairs.length - maxLines} more lines)
        </Text>
      )}
    </Box>
  );
});

export default SideBySideDiff;

// Export types for convenience
export type { SideBySideDiffProps, AlignedPair };
