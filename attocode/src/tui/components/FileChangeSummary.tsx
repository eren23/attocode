/**
 * FileChangeSummary Component
 *
 * Displays a summary of all files changed during a session.
 * Shows total additions/deletions and per-file breakdown.
 *
 * Features:
 * - Collapsed mode: Just totals
 * - Expanded mode: Full file list with stats
 * - Visual indicators for new vs modified files
 * - Sortable by various criteria
 *
 * @example
 * ```tsx
 * <FileChangeSummary
 *   changes={[
 *     { path: 'src/index.ts', additions: 10, deletions: 5, type: 'modify' },
 *     { path: 'src/new.ts', additions: 50, deletions: 0, type: 'create' },
 *   ]}
 *   expanded={true}
 * />
 * ```
 */

import { memo, useMemo } from 'react';
import { Box, Text } from 'ink';

// =============================================================================
// TYPES
// =============================================================================

export interface FileChange {
  /** File path (relative to project root) */
  path: string;
  /** Number of lines added */
  additions: number;
  /** Number of lines deleted */
  deletions: number;
  /** Type of change */
  type: 'create' | 'modify' | 'delete' | 'rename';
  /** For renames, the original path */
  oldPath?: string;
}

export interface FileChangeSummaryProps {
  /** List of file changes */
  changes: FileChange[];
  /** Whether to show expanded view with per-file details */
  expanded?: boolean;
  /** Sort order for file list */
  sortBy?: 'path' | 'additions' | 'deletions' | 'total';
  /** Maximum files to show in expanded view */
  maxFiles?: number;
}

// =============================================================================
// COLORS
// =============================================================================

const COLORS = {
  addition: '#98FB98',
  deletion: '#FF6B6B',
  create: '#87CEEB',
  modify: '#DDA0DD',
  delete: '#FF6B6B',
  rename: '#FFD700',
  border: '#444444',
  muted: '#666666',
};

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

/**
 * Get status indicator for a file change type.
 */
function getStatusIndicator(type: FileChange['type']): { char: string; color: string } {
  switch (type) {
    case 'create':
      return { char: 'A', color: COLORS.create };
    case 'modify':
      return { char: 'M', color: COLORS.modify };
    case 'delete':
      return { char: 'D', color: COLORS.delete };
    case 'rename':
      return { char: 'R', color: COLORS.rename };
  }
}

/**
 * Sort file changes by specified criteria.
 */
function sortChanges(
  changes: FileChange[],
  sortBy: FileChangeSummaryProps['sortBy']
): FileChange[] {
  const sorted = [...changes];

  switch (sortBy) {
    case 'additions':
      return sorted.sort((a, b) => b.additions - a.additions);
    case 'deletions':
      return sorted.sort((a, b) => b.deletions - a.deletions);
    case 'total':
      return sorted.sort(
        (a, b) => (b.additions + b.deletions) - (a.additions + a.deletions)
      );
    case 'path':
    default:
      return sorted.sort((a, b) => a.path.localeCompare(b.path));
  }
}

/**
 * Truncate path for display, showing end of path.
 */
function truncatePath(path: string, maxWidth: number): string {
  if (path.length <= maxWidth) return path;
  return '…' + path.slice(-(maxWidth - 1));
}

// =============================================================================
// SUB-COMPONENTS
// =============================================================================

/**
 * Render a single file change row.
 */
const FileChangeRow = memo(function FileChangeRow({
  change,
  maxPathWidth,
}: {
  change: FileChange;
  maxPathWidth: number;
}) {
  const status = getStatusIndicator(change.type);
  const displayPath = change.type === 'rename' && change.oldPath
    ? `${truncatePath(change.oldPath, maxPathWidth / 2 - 2)} → ${truncatePath(change.path, maxPathWidth / 2 - 2)}`
    : truncatePath(change.path, maxPathWidth);

  return (
    <Box>
      {/* Status indicator */}
      <Text color={status.color} bold>
        {status.char}
      </Text>
      <Text> </Text>

      {/* File path */}
      <Text color={COLORS.muted}>{displayPath}</Text>
      <Text> </Text>

      {/* Stats */}
      {change.additions > 0 && (
        <Text color={COLORS.addition}>+{change.additions}</Text>
      )}
      {change.additions > 0 && change.deletions > 0 && (
        <Text color={COLORS.muted}>/</Text>
      )}
      {change.deletions > 0 && (
        <Text color={COLORS.deletion}>-{change.deletions}</Text>
      )}
    </Box>
  );
});

/**
 * Render a visual stats bar.
 */
const StatsBar = memo(function StatsBar({
  additions,
  deletions,
  maxWidth = 20,
}: {
  additions: number;
  deletions: number;
  maxWidth?: number;
}) {
  const total = additions + deletions;
  if (total === 0) return null;

  const addWidth = Math.round((additions / total) * maxWidth);
  const delWidth = maxWidth - addWidth;

  return (
    <Box>
      <Text backgroundColor={COLORS.addition}>
        {' '.repeat(Math.max(1, addWidth))}
      </Text>
      <Text backgroundColor={COLORS.deletion}>
        {' '.repeat(Math.max(1, delWidth))}
      </Text>
    </Box>
  );
});

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export const FileChangeSummary = memo(function FileChangeSummary({
  changes,
  expanded = false,
  sortBy = 'path',
  maxFiles = 20,
}: FileChangeSummaryProps) {
  // Calculate totals
  const stats = useMemo(() => {
    let additions = 0;
    let deletions = 0;
    let created = 0;
    let modified = 0;
    let deleted = 0;
    let renamed = 0;

    for (const change of changes) {
      additions += change.additions;
      deletions += change.deletions;

      switch (change.type) {
        case 'create': created++; break;
        case 'modify': modified++; break;
        case 'delete': deleted++; break;
        case 'rename': renamed++; break;
      }
    }

    return { additions, deletions, created, modified, deleted, renamed };
  }, [changes]);

  // Sort and limit changes for display
  const displayChanges = useMemo(() => {
    const sorted = sortChanges(changes, sortBy);
    return sorted.slice(0, maxFiles);
  }, [changes, sortBy, maxFiles]);

  const hasMore = changes.length > maxFiles;

  // Empty state
  if (changes.length === 0) {
    return (
      <Box borderStyle="round" borderColor={COLORS.border} paddingX={1}>
        <Text color={COLORS.muted} dimColor>No changes in this session</Text>
      </Box>
    );
  }

  return (
    <Box
      flexDirection="column"
      borderStyle="round"
      borderColor={COLORS.border}
      paddingX={1}
    >
      {/* Header with totals */}
      <Box>
        <Text bold>Session Changes: </Text>
        <Text color={COLORS.addition}>+{stats.additions}</Text>
        <Text color={COLORS.muted}>/</Text>
        <Text color={COLORS.deletion}>-{stats.deletions}</Text>
        <Text color={COLORS.muted}> in </Text>
        <Text>{changes.length} file{changes.length !== 1 ? 's' : ''}</Text>
      </Box>

      {/* Stats bar */}
      <Box marginTop={1}>
        <StatsBar
          additions={stats.additions}
          deletions={stats.deletions}
          maxWidth={30}
        />
      </Box>

      {/* Type breakdown */}
      <Box marginTop={1}>
        {stats.created > 0 && (
          <Text color={COLORS.create}>{stats.created} new </Text>
        )}
        {stats.modified > 0 && (
          <Text color={COLORS.modify}>{stats.modified} modified </Text>
        )}
        {stats.deleted > 0 && (
          <Text color={COLORS.delete}>{stats.deleted} deleted </Text>
        )}
        {stats.renamed > 0 && (
          <Text color={COLORS.rename}>{stats.renamed} renamed </Text>
        )}
      </Box>

      {/* Expanded file list */}
      {expanded && (
        <Box flexDirection="column" marginTop={1}>
          {displayChanges.map((change, i) => (
            <FileChangeRow
              key={`${change.path}-${i}`}
              change={change}
              maxPathWidth={50}
            />
          ))}

          {hasMore && (
            <Text color={COLORS.muted} dimColor>
              ... and {changes.length - maxFiles} more files
            </Text>
          )}
        </Box>
      )}
    </Box>
  );
});

export default FileChangeSummary;
