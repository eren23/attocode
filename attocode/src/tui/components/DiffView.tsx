/**
 * DiffView Component
 *
 * Displays unified diff with color coding for additions/deletions.
 * Supports:
 * - Collapsed summary (+N/-M) or expanded full diff
 * - Line numbers (optional)
 * - Word-level diff highlighting within modified lines
 * - Parsed UnifiedDiff format for structured rendering
 *
 * @example
 * ```tsx
 * // Simple string diff
 * <DiffView diff={diffString} expanded={true} />
 *
 * // With line numbers
 * <DiffView diff={diffString} expanded={true} showLineNumbers={true} />
 *
 * // With word-level highlighting (shows exactly what changed within lines)
 * <DiffView parsedDiff={parsed} expanded={true} showWordDiff={true} />
 *
 * // Full featured: line numbers + word diff
 * const parsed = parseUnifiedDiff(diffString);
 * <DiffView parsedDiff={parsed[0]} expanded={true} showLineNumbers={true} showWordDiff={true} />
 * ```
 */

import React, { memo, useMemo } from 'react';
import { Box, Text } from 'ink';
import { diffWords, type Change } from 'diff';
import type { UnifiedDiff, DiffHunk, DiffLine } from '../../integrations/diff-utils.js';
import type { ThemeColors } from '../types.js';
import { tokenize, detectLanguage, getTokenColor, type Token } from '../syntax/index.js';

interface DiffViewProps {
  /** The unified diff string (use this OR parsedDiff) */
  diff?: string;
  /** Pre-parsed diff (use this OR diff) */
  parsedDiff?: UnifiedDiff;
  /** Whether to show full diff (true) or just summary (false) */
  expanded: boolean;
  /** Maximum lines to show in expanded view */
  maxLines?: number;
  /** Show line numbers in the gutter */
  showLineNumbers?: boolean;
  /** Width for line number columns (default: 4) */
  lineNumberWidth?: number;
  /** Enable word-level diff highlighting within modified lines */
  showWordDiff?: boolean;
  /** Enable syntax highlighting for code */
  syntaxHighlight?: boolean;
  /** Theme colors for syntax highlighting */
  theme?: ThemeColors;
  /** File path for language detection (used when syntaxHighlight is true) */
  filePath?: string;
}

// =============================================================================
// COLORS
// =============================================================================

const COLORS = {
  addition: '#98FB98',      // Green for additions
  deletion: '#FF6B6B',      // Red for deletions
  context: '#666666',       // Gray for context
  hunkHeader: '#87CEEB',    // Cyan for @@ lines
  fileHeader: '#DDA0DD',    // Purple for --- +++ lines
  lineNumber: '#555555',    // Dim for line numbers
};

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

/**
 * Parse diff statistics from a unified diff string.
 */
function parseDiffStats(diff: string): { additions: number; deletions: number } {
  const lines = diff.split('\n');
  let additions = 0;
  let deletions = 0;

  for (const line of lines) {
    if (line.startsWith('+') && !line.startsWith('+++')) {
      additions++;
    } else if (line.startsWith('-') && !line.startsWith('---')) {
      deletions++;
    }
  }

  return { additions, deletions };
}

/**
 * Get stats from a parsed diff.
 */
function getParsedDiffStats(diff: UnifiedDiff): { additions: number; deletions: number } {
  let additions = 0;
  let deletions = 0;

  for (const hunk of diff.hunks) {
    for (const line of hunk.lines) {
      if (line.type === 'add') additions++;
      else if (line.type === 'remove') deletions++;
    }
  }

  return { additions, deletions };
}

/**
 * Get color for a diff line based on its prefix.
 */
function getDiffLineColor(line: string): string {
  if (line.startsWith('+') && !line.startsWith('+++')) {
    return COLORS.addition;
  }
  if (line.startsWith('-') && !line.startsWith('---')) {
    return COLORS.deletion;
  }
  if (line.startsWith('@@')) {
    return COLORS.hunkHeader;
  }
  if (line.startsWith('---') || line.startsWith('+++')) {
    return COLORS.fileHeader;
  }
  return COLORS.context;
}

/**
 * Get color for a DiffLine type.
 */
function getLineTypeColor(type: DiffLine['type']): string {
  switch (type) {
    case 'add': return COLORS.addition;
    case 'remove': return COLORS.deletion;
    default: return COLORS.context;
  }
}

/**
 * Get prefix character for a DiffLine type.
 */
function getLinePrefix(type: DiffLine['type']): string {
  switch (type) {
    case 'add': return '+';
    case 'remove': return '-';
    default: return ' ';
  }
}

/**
 * Pair up adjacent removed and added lines for word-level diffing.
 * Returns Map<lineIndex, pairedLineContent> for lines that should show word diffs.
 */
function findLinePairs(lines: DiffLine[]): Map<number, string> {
  const pairs = new Map<number, string>();

  for (let i = 0; i < lines.length - 1; i++) {
    const current = lines[i];
    const next = lines[i + 1];

    // If we have a remove followed by an add, they're likely a modification
    if (current.type === 'remove' && next.type === 'add') {
      pairs.set(i, next.content);      // removed line paired with added content
      pairs.set(i + 1, current.content); // added line paired with removed content
    }
  }

  return pairs;
}

/**
 * Render word-level diff between old and new content.
 */
function renderWordDiff(
  oldContent: string,
  newContent: string,
  lineType: 'add' | 'remove'
): React.ReactNode {
  const changes = diffWords(oldContent, newContent);

  return changes.map((change: Change, i: number) => {
    // For a removed line, highlight what was removed
    // For an added line, highlight what was added
    if (lineType === 'remove') {
      if (change.removed) {
        // This part was removed - highlight it strongly
        return (
          <Text key={i} color={COLORS.deletion} bold inverse>
            {change.value}
          </Text>
        );
      } else if (change.added) {
        // This part was added in the new version - don't show on removed line
        return null;
      }
      // Unchanged part
      return <Text key={i} color={COLORS.deletion}>{change.value}</Text>;
    } else {
      // lineType === 'add'
      if (change.added) {
        // This part was added - highlight it strongly
        return (
          <Text key={i} color={COLORS.addition} bold inverse>
            {change.value}
          </Text>
        );
      } else if (change.removed) {
        // This part was in the old version - don't show on added line
        return null;
      }
      // Unchanged part
      return <Text key={i} color={COLORS.addition}>{change.value}</Text>;
    }
  });
}

/**
 * Render content with syntax highlighting.
 */
function renderSyntaxHighlight(
  content: string,
  theme: ThemeColors,
  language: string | null,
  baseColor?: string
): React.ReactNode {
  if (!language) {
    return <Text color={baseColor}>{content}</Text>;
  }

  const tokens = tokenize(content, language);

  return tokens.map((token: Token, i: number) => (
    <Text key={i} color={getTokenColor(token.type, theme)}>
      {token.content}
    </Text>
  ));
}

/**
 * Render word-level diff with syntax highlighting.
 * Combines word-diff highlighting with syntax colors.
 */
function renderWordDiffWithSyntax(
  oldContent: string,
  newContent: string,
  lineType: 'add' | 'remove',
  theme: ThemeColors,
  language: string | null
): React.ReactNode {
  const changes = diffWords(oldContent, newContent);
  const elements: React.ReactNode[] = [];
  let keyIndex = 0;

  for (const change of changes) {
    if (lineType === 'remove') {
      if (change.removed) {
        // Removed content - use inverse highlighting
        elements.push(
          <Text key={keyIndex++} color={COLORS.deletion} bold inverse>
            {change.value}
          </Text>
        );
      } else if (change.added) {
        // Skip added content on removed line
        continue;
      } else {
        // Unchanged - apply syntax highlighting
        if (language) {
          const tokens = tokenize(change.value, language);
          for (const token of tokens) {
            elements.push(
              <Text key={keyIndex++} color={getTokenColor(token.type, theme)}>
                {token.content}
              </Text>
            );
          }
        } else {
          elements.push(
            <Text key={keyIndex++} color={COLORS.deletion}>
              {change.value}
            </Text>
          );
        }
      }
    } else {
      // lineType === 'add'
      if (change.added) {
        // Added content - use inverse highlighting
        elements.push(
          <Text key={keyIndex++} color={COLORS.addition} bold inverse>
            {change.value}
          </Text>
        );
      } else if (change.removed) {
        // Skip removed content on added line
        continue;
      } else {
        // Unchanged - apply syntax highlighting
        if (language) {
          const tokens = tokenize(change.value, language);
          for (const token of tokens) {
            elements.push(
              <Text key={keyIndex++} color={getTokenColor(token.type, theme)}>
                {token.content}
              </Text>
            );
          }
        } else {
          elements.push(
            <Text key={keyIndex++} color={COLORS.addition}>
              {change.value}
            </Text>
          );
        }
      }
    }
  }

  return <>{elements}</>;
}

// =============================================================================
// SUB-COMPONENTS
// =============================================================================

/**
 * Render diff summary (collapsed view).
 */
const DiffSummary = memo(function DiffSummary({
  additions,
  deletions,
}: {
  additions: number;
  deletions: number;
}) {
  return (
    <Text>
      <Text color={COLORS.addition}>+{additions}</Text>
      <Text color={COLORS.context}>/</Text>
      <Text color={COLORS.deletion}>-{deletions}</Text>
    </Text>
  );
});

/**
 * Render a single diff line with optional line numbers and word-level highlighting.
 */
const DiffLineView = memo(function DiffLineView({
  line,
  showLineNumbers,
  lineNumberWidth = 4,
  pairedContent,
  showWordDiff,
  syntaxHighlight,
  theme,
  language,
}: {
  line: DiffLine;
  showLineNumbers?: boolean;
  lineNumberWidth?: number;
  /** Content from the paired line (for word-level diff) */
  pairedContent?: string;
  /** Whether to show word-level diff highlighting */
  showWordDiff?: boolean;
  /** Whether to show syntax highlighting */
  syntaxHighlight?: boolean;
  /** Theme colors for syntax highlighting */
  theme?: ThemeColors;
  /** Detected language for syntax highlighting */
  language?: string | null;
}) {
  const color = getLineTypeColor(line.type);
  const prefix = getLinePrefix(line.type);

  // Determine if we should render word-level diff
  const useWordDiff = showWordDiff && pairedContent !== undefined &&
    (line.type === 'add' || line.type === 'remove');

  // Determine if we should use syntax highlighting
  const useSyntax = syntaxHighlight && theme && language;

  // Render the content
  let contentNode: React.ReactNode;

  if (useWordDiff && useSyntax) {
    // Word diff with syntax highlighting
    contentNode = (
      <Text>
        <Text color={color}>{prefix}</Text>
        {renderWordDiffWithSyntax(
          line.type === 'remove' ? line.content : pairedContent,
          line.type === 'add' ? line.content : pairedContent,
          line.type as 'add' | 'remove',
          theme,
          language
        )}
      </Text>
    );
  } else if (useWordDiff) {
    // Word diff without syntax
    contentNode = (
      <Text>
        <Text color={color}>{prefix}</Text>
        {renderWordDiff(
          line.type === 'remove' ? line.content : pairedContent,
          line.type === 'add' ? line.content : pairedContent,
          line.type as 'add' | 'remove'
        )}
      </Text>
    );
  } else if (useSyntax) {
    // Syntax highlighting without word diff
    contentNode = (
      <Text>
        <Text color={color}>{prefix}</Text>
        {renderSyntaxHighlight(line.content, theme, language, color)}
      </Text>
    );
  } else {
    // Plain text
    contentNode = <Text color={color}>{prefix}{line.content}</Text>;
  }

  if (showLineNumbers) {
    const oldNum = line.oldLineNumber?.toString().padStart(lineNumberWidth) ?? ' '.repeat(lineNumberWidth);
    const newNum = line.newLineNumber?.toString().padStart(lineNumberWidth) ?? ' '.repeat(lineNumberWidth);

    return (
      <Box>
        <Text color={COLORS.lineNumber} dimColor>{oldNum}</Text>
        <Text> </Text>
        <Text color={COLORS.lineNumber} dimColor>{newNum}</Text>
        <Text> </Text>
        {contentNode}
      </Box>
    );
  }

  return contentNode;
});

/**
 * Render a hunk header (@@...@@).
 */
const HunkHeaderView = memo(function HunkHeaderView({
  hunk,
  showLineNumbers,
  lineNumberWidth = 4,
}: {
  hunk: DiffHunk;
  showLineNumbers?: boolean;
  lineNumberWidth?: number;
}) {
  const header = `@@ -${hunk.oldStart},${hunk.oldCount} +${hunk.newStart},${hunk.newCount} @@`;
  const gutterWidth = showLineNumbers ? (lineNumberWidth * 2 + 2) : 0;

  return (
    <Box>
      {showLineNumbers && <Text color={COLORS.lineNumber}>{' '.repeat(gutterWidth)}</Text>}
      <Text color={COLORS.hunkHeader}>{header}</Text>
    </Box>
  );
});

/**
 * Render a single hunk.
 */
const HunkView = memo(function HunkView({
  hunk,
  showLineNumbers,
  lineNumberWidth,
  maxLines,
  showWordDiff,
  syntaxHighlight,
  theme,
  language,
}: {
  hunk: DiffHunk;
  showLineNumbers?: boolean;
  lineNumberWidth?: number;
  maxLines?: number;
  showWordDiff?: boolean;
  syntaxHighlight?: boolean;
  theme?: ThemeColors;
  language?: string | null;
}) {
  const linesToShow = maxLines ? hunk.lines.slice(0, maxLines) : hunk.lines;
  const hasMore = maxLines && hunk.lines.length > maxLines;

  // Pre-compute line pairs for word-level diffing
  const linePairs = useMemo(() => {
    if (!showWordDiff) return new Map<number, string>();
    return findLinePairs(linesToShow);
  }, [showWordDiff, linesToShow]);

  return (
    <Box flexDirection="column">
      <HunkHeaderView
        hunk={hunk}
        showLineNumbers={showLineNumbers}
        lineNumberWidth={lineNumberWidth}
      />
      {linesToShow.map((line, i) => (
        <DiffLineView
          key={i}
          line={line}
          showLineNumbers={showLineNumbers}
          lineNumberWidth={lineNumberWidth}
          pairedContent={linePairs.get(i)}
          showWordDiff={showWordDiff}
          syntaxHighlight={syntaxHighlight}
          theme={theme}
          language={language}
        />
      ))}
      {hasMore && (
        <Text color={COLORS.context} dimColor>
          ... ({hunk.lines.length - (maxLines ?? 0)} more lines in hunk)
        </Text>
      )}
    </Box>
  );
});

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export const DiffView = memo(function DiffView({
  diff,
  parsedDiff,
  expanded,
  maxLines = 50,
  showLineNumbers = false,
  lineNumberWidth = 4,
  showWordDiff = false,
  syntaxHighlight = false,
  theme,
  filePath,
}: DiffViewProps) {
  // Use parsed diff if provided, otherwise fall back to string diff
  const hasParsedDiff = parsedDiff !== undefined;
  const hasStringDiff = diff !== undefined && diff.trim().length > 0;

  // Detect language for syntax highlighting
  const detectedLanguage = useMemo(() => {
    if (!syntaxHighlight) return null;
    // Try to detect from filePath prop first
    if (filePath) {
      return detectLanguage(filePath);
    }
    // Fall back to parsed diff paths
    if (hasParsedDiff) {
      const path = parsedDiff.newPath || parsedDiff.oldPath;
      if (path) return detectLanguage(path);
    }
    return null;
  }, [syntaxHighlight, filePath, hasParsedDiff, parsedDiff]);

  // Compute stats
  const stats = useMemo(() => {
    if (hasParsedDiff) {
      return getParsedDiffStats(parsedDiff);
    }
    if (hasStringDiff) {
      return parseDiffStats(diff);
    }
    return { additions: 0, deletions: 0 };
  }, [diff, parsedDiff, hasParsedDiff, hasStringDiff]);

  // No content
  if (!hasParsedDiff && !hasStringDiff) {
    return <Text color={COLORS.context} dimColor>No changes</Text>;
  }

  // Collapsed view: just show +N/-M summary
  if (!expanded) {
    return <DiffSummary additions={stats.additions} deletions={stats.deletions} />;
  }

  // Expanded view with parsed diff (structured rendering)
  if (hasParsedDiff) {
    const linesPerHunk = maxLines ? Math.ceil(maxLines / Math.max(parsedDiff.hunks.length, 1)) : undefined;

    return (
      <Box flexDirection="column" marginTop={1}>
        {/* Summary header */}
        <Box gap={1}>
          <Text color={COLORS.fileHeader} bold>
            {parsedDiff.isNewFile ? 'New: ' : parsedDiff.isDeletedFile ? 'Deleted: ' : 'Modified: '}
            {parsedDiff.newPath}
          </Text>
          <DiffSummary additions={stats.additions} deletions={stats.deletions} />
        </Box>

        {/* Hunks */}
        <Box flexDirection="column" marginLeft={1} marginTop={1}>
          {parsedDiff.hunks.map((hunk, i) => (
            <HunkView
              key={i}
              hunk={hunk}
              showLineNumbers={showLineNumbers}
              lineNumberWidth={lineNumberWidth}
              maxLines={linesPerHunk}
              showWordDiff={showWordDiff}
              syntaxHighlight={syntaxHighlight}
              theme={theme}
              language={detectedLanguage}
            />
          ))}
        </Box>
      </Box>
    );
  }

  // Expanded view with string diff (legacy rendering)
  const lines = diff!.split('\n');
  const displayLines = lines.slice(0, maxLines);
  const hasMore = lines.length > maxLines;

  return (
    <Box flexDirection="column" marginTop={1}>
      {/* Summary header */}
      <Box gap={1}>
        <Text color={COLORS.fileHeader} bold>Diff:</Text>
        <DiffSummary additions={stats.additions} deletions={stats.deletions} />
      </Box>

      {/* Diff content */}
      <Box flexDirection="column" marginLeft={2} marginTop={1}>
        {displayLines.map((line, i) => (
          <Text key={i} color={getDiffLineColor(line)}>
            {line || ' '}
          </Text>
        ))}
        {hasMore && (
          <Text color={COLORS.context} dimColor>
            ... ({lines.length - maxLines} more lines)
          </Text>
        )}
      </Box>
    </Box>
  );
});

export default DiffView;

// Re-export types for convenience
export type { UnifiedDiff, DiffHunk, DiffLine };
