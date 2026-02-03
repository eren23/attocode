/**
 * CollapsibleDiffView Component
 *
 * Enhanced diff view with collapsible hunks for easier navigation.
 * Each hunk can be independently expanded/collapsed.
 *
 * Features:
 * - Per-hunk collapse/expand state
 * - Hunk statistics summary when collapsed
 * - Visual indicators for expand/collapse state
 * - Supports line numbers and word-level diffs
 *
 * @example
 * ```tsx
 * <CollapsibleDiffView
 *   parsedDiff={diff}
 *   defaultExpanded={false}
 *   showLineNumbers={true}
 *   showWordDiff={true}
 * />
 * ```
 */

import React, { memo, useMemo, useState, useCallback } from 'react';
import { Box, Text } from 'ink';
import { diffWords } from 'diff';
import type { UnifiedDiff, DiffHunk, DiffLine } from '../../integrations/diff-utils.js';
import type { ThemeColors } from '../types.js';
import { tokenize, detectLanguage, getTokenColor, type Token } from '../syntax/index.js';

// =============================================================================
// TYPES
// =============================================================================

interface CollapsibleDiffViewProps {
  /** The parsed diff to display */
  parsedDiff: UnifiedDiff;
  /** Whether hunks start expanded (default: true) */
  defaultExpanded?: boolean;
  /** Show line numbers in the gutter */
  showLineNumbers?: boolean;
  /** Enable word-level diff highlighting */
  showWordDiff?: boolean;
  /** Width for line number columns */
  lineNumberWidth?: number;
  /** Maximum lines per hunk when expanded */
  maxLinesPerHunk?: number;
  /** Enable syntax highlighting for code */
  syntaxHighlight?: boolean;
  /** Theme colors for syntax highlighting */
  theme?: ThemeColors;
  /** File path for language detection */
  filePath?: string;
}

interface HunkStats {
  additions: number;
  deletions: number;
  context: number;
}

// =============================================================================
// COLORS
// =============================================================================

const COLORS = {
  addition: '#98FB98',
  deletion: '#FF6B6B',
  context: '#666666',
  hunkHeader: '#87CEEB',
  fileHeader: '#DDA0DD',
  lineNumber: '#555555',
  collapsed: '#888888',
  expandIndicator: '#FFD700',
};

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

/**
 * Calculate statistics for a hunk.
 */
function calculateHunkStats(hunk: DiffHunk): HunkStats {
  let additions = 0;
  let deletions = 0;
  let context = 0;

  for (const line of hunk.lines) {
    switch (line.type) {
      case 'add': additions++; break;
      case 'remove': deletions++; break;
      default: context++; break;
    }
  }

  return { additions, deletions, context };
}

/**
 * Get color for a diff line type.
 */
function getLineTypeColor(type: DiffLine['type']): string {
  switch (type) {
    case 'add': return COLORS.addition;
    case 'remove': return COLORS.deletion;
    default: return COLORS.context;
  }
}

/**
 * Get prefix character for a diff line type.
 */
function getLinePrefix(type: DiffLine['type']): string {
  switch (type) {
    case 'add': return '+';
    case 'remove': return '-';
    default: return ' ';
  }
}

/**
 * Find line pairs for word-level diffing.
 */
function findLinePairs(lines: DiffLine[]): Map<number, string> {
  const pairs = new Map<number, string>();

  for (let i = 0; i < lines.length - 1; i++) {
    const current = lines[i];
    const next = lines[i + 1];

    if (current.type === 'remove' && next.type === 'add') {
      pairs.set(i, next.content);
      pairs.set(i + 1, current.content);
    }
  }

  return pairs;
}

/**
 * Render word-level diff highlighting.
 */
function renderWordDiff(
  oldContent: string,
  newContent: string,
  lineType: 'add' | 'remove'
): React.ReactNode {
  const changes = diffWords(oldContent, newContent);

  return changes.map((change, i) => {
    if (lineType === 'remove') {
      if (change.removed) {
        return (
          <Text key={i} color={COLORS.deletion} bold inverse>
            {change.value}
          </Text>
        );
      } else if (change.added) {
        return null;
      }
      return <Text key={i} color={COLORS.deletion}>{change.value}</Text>;
    } else {
      if (change.added) {
        return (
          <Text key={i} color={COLORS.addition} bold inverse>
            {change.value}
          </Text>
        );
      } else if (change.removed) {
        return null;
      }
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
  language: string,
  _baseColor?: string
): React.ReactNode {
  const tokens = tokenize(content, language);
  return tokens.map((token: Token, i: number) => (
    <Text key={i} color={getTokenColor(token.type, theme)}>
      {token.content}
    </Text>
  ));
}

/**
 * Render word-level diff with syntax highlighting.
 */
function renderWordDiffWithSyntax(
  oldContent: string,
  newContent: string,
  lineType: 'add' | 'remove',
  theme: ThemeColors,
  language: string
): React.ReactNode {
  const changes = diffWords(oldContent, newContent);
  const elements: React.ReactNode[] = [];
  let keyIndex = 0;

  for (const change of changes) {
    if (lineType === 'remove') {
      if (change.removed) {
        elements.push(
          <Text key={keyIndex++} color={COLORS.deletion} bold inverse>
            {change.value}
          </Text>
        );
      } else if (change.added) {
        continue;
      } else {
        // Unchanged - apply syntax highlighting
        const tokens = tokenize(change.value, language);
        for (const token of tokens) {
          elements.push(
            <Text key={keyIndex++} color={getTokenColor(token.type, theme)}>
              {token.content}
            </Text>
          );
        }
      }
    } else {
      if (change.added) {
        elements.push(
          <Text key={keyIndex++} color={COLORS.addition} bold inverse>
            {change.value}
          </Text>
        );
      } else if (change.removed) {
        continue;
      } else {
        // Unchanged - apply syntax highlighting
        const tokens = tokenize(change.value, language);
        for (const token of tokens) {
          elements.push(
            <Text key={keyIndex++} color={getTokenColor(token.type, theme)}>
              {token.content}
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
 * Render a single diff line.
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
  pairedContent?: string;
  showWordDiff?: boolean;
  syntaxHighlight?: boolean;
  theme?: ThemeColors;
  language?: string | null;
}) {
  const color = getLineTypeColor(line.type);
  const prefix = getLinePrefix(line.type);

  const useWordDiff = showWordDiff && pairedContent !== undefined &&
    (line.type === 'add' || line.type === 'remove');

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
 * Render a collapsible hunk.
 */
const CollapsibleHunk = memo(function CollapsibleHunk({
  hunk,
  hunkIndex,
  expanded,
  onToggle,
  showLineNumbers,
  lineNumberWidth,
  showWordDiff,
  maxLines,
  syntaxHighlight,
  theme,
  language,
}: {
  hunk: DiffHunk;
  hunkIndex: number;
  expanded: boolean;
  onToggle: (index: number) => void;
  showLineNumbers?: boolean;
  lineNumberWidth?: number;
  showWordDiff?: boolean;
  maxLines?: number;
  syntaxHighlight?: boolean;
  theme?: ThemeColors;
  language?: string | null;
}) {
  // Note: onToggle and hunkIndex are available for parent component to wire up
  // keyboard navigation (e.g., press Enter on focused hunk)
  void onToggle; // Acknowledge prop for future use
  void hunkIndex;
  const stats = useMemo(() => calculateHunkStats(hunk), [hunk]);

  const linePairs = useMemo(() => {
    if (!showWordDiff || !expanded) return new Map<number, string>();
    return findLinePairs(hunk.lines);
  }, [showWordDiff, expanded, hunk.lines]);

  const linesToShow = maxLines && expanded ? hunk.lines.slice(0, maxLines) : hunk.lines;
  const hasMore = maxLines && hunk.lines.length > maxLines;

  const gutterWidth = showLineNumbers ? ((lineNumberWidth ?? 4) * 2 + 2) : 0;

  return (
    <Box flexDirection="column">
      {/* Hunk header - clickable */}
      <Box>
        {showLineNumbers && <Text color={COLORS.lineNumber}>{' '.repeat(gutterWidth)}</Text>}
        <Text color={COLORS.expandIndicator} bold>
          {expanded ? '[-] ' : '[+] '}
        </Text>
        <Text color={COLORS.hunkHeader}>
          @@ -{hunk.oldStart},{hunk.oldCount} +{hunk.newStart},{hunk.newCount} @@
        </Text>
        {!expanded && (
          <Text color={COLORS.collapsed} dimColor>
            {' '}({stats.additions} additions, {stats.deletions} deletions)
          </Text>
        )}
      </Box>

      {/* Hunk content - only when expanded */}
      {expanded && (
        <Box flexDirection="column">
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
      )}
    </Box>
  );
});

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export const CollapsibleDiffView = memo(function CollapsibleDiffView({
  parsedDiff,
  defaultExpanded = true,
  showLineNumbers = false,
  showWordDiff = false,
  lineNumberWidth = 4,
  maxLinesPerHunk,
  syntaxHighlight = false,
  theme,
  filePath,
}: CollapsibleDiffViewProps) {
  // Track expanded state for each hunk
  const [expandedHunks, setExpandedHunks] = useState<Set<number>>(() => {
    if (defaultExpanded) {
      return new Set(parsedDiff.hunks.map((_, i) => i));
    }
    return new Set();
  });

  // Detect language for syntax highlighting
  const detectedLanguage = useMemo(() => {
    if (!syntaxHighlight) return null;
    // Try filePath first
    if (filePath) {
      return detectLanguage(filePath);
    }
    // Fall back to parsed diff paths
    const path = parsedDiff.newPath || parsedDiff.oldPath;
    if (path) return detectLanguage(path);
    return null;
  }, [syntaxHighlight, filePath, parsedDiff.newPath, parsedDiff.oldPath]);

  // Toggle a hunk's expanded state
  const toggleHunk = useCallback((index: number) => {
    setExpandedHunks(prev => {
      const next = new Set(prev);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  }, []);

  // Expand all hunks
  const expandAll = useCallback(() => {
    setExpandedHunks(new Set(parsedDiff.hunks.map((_, i) => i)));
  }, [parsedDiff.hunks]);

  // Collapse all hunks
  const collapseAll = useCallback(() => {
    setExpandedHunks(new Set());
  }, []);

  // These are available for keyboard navigation (e.g., 'e' to expand all, 'c' to collapse)
  void expandAll;
  void collapseAll;

  // Calculate total stats
  const totalStats = useMemo(() => {
    let additions = 0;
    let deletions = 0;

    for (const hunk of parsedDiff.hunks) {
      const stats = calculateHunkStats(hunk);
      additions += stats.additions;
      deletions += stats.deletions;
    }

    return { additions, deletions };
  }, [parsedDiff.hunks]);

  const allExpanded = expandedHunks.size === parsedDiff.hunks.length;
  const allCollapsed = expandedHunks.size === 0;

  return (
    <Box flexDirection="column">
      {/* File header */}
      <Box gap={1}>
        <Text color={COLORS.fileHeader} bold>
          {parsedDiff.isNewFile ? 'New: ' : parsedDiff.isDeletedFile ? 'Deleted: ' : 'Modified: '}
          {parsedDiff.newPath}
        </Text>
        <DiffSummary additions={totalStats.additions} deletions={totalStats.deletions} />
      </Box>

      {/* Expand/Collapse all controls */}
      <Box marginTop={1}>
        <Text color={COLORS.collapsed} dimColor>
          {parsedDiff.hunks.length} hunk{parsedDiff.hunks.length !== 1 ? 's' : ''}
          {' | '}
        </Text>
        {!allExpanded && (
          <Text color={COLORS.expandIndicator} dimColor>
            [expand all]
          </Text>
        )}
        {!allExpanded && !allCollapsed && <Text color={COLORS.collapsed}> </Text>}
        {!allCollapsed && (
          <Text color={COLORS.expandIndicator} dimColor>
            [collapse all]
          </Text>
        )}
      </Box>

      {/* Hunks */}
      <Box flexDirection="column" marginLeft={1} marginTop={1}>
        {parsedDiff.hunks.map((hunk, i) => (
          <CollapsibleHunk
            key={i}
            hunk={hunk}
            hunkIndex={i}
            expanded={expandedHunks.has(i)}
            onToggle={toggleHunk}
            showLineNumbers={showLineNumbers}
            lineNumberWidth={lineNumberWidth}
            showWordDiff={showWordDiff}
            maxLines={maxLinesPerHunk}
            syntaxHighlight={syntaxHighlight}
            theme={theme}
            language={detectedLanguage}
          />
        ))}
      </Box>
    </Box>
  );
});

export default CollapsibleDiffView;

// Export types
export type { CollapsibleDiffViewProps };
