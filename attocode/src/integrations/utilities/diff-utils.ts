/**
 * Unified Diff Utilities
 *
 * Parse, generate, and apply unified diffs.
 * Useful for code review, patch application, and version comparison.
 *
 * @example
 * ```typescript
 * const diff = parseUnifiedDiff(diffText);
 * const newContent = applyDiff(originalContent, diff[0]);
 * ```
 */

// =============================================================================
// TYPES
// =============================================================================

/**
 * A single hunk in a unified diff.
 */
export interface DiffHunk {
  /** Original file start line (1-indexed) */
  oldStart: number;
  /** Number of lines in original */
  oldCount: number;
  /** New file start line (1-indexed) */
  newStart: number;
  /** Number of lines in new */
  newCount: number;
  /** Lines in the hunk (with prefix +/-/space) */
  lines: DiffLine[];
}

/**
 * A single line in a diff hunk.
 */
export interface DiffLine {
  /** Line type: add, remove, or context */
  type: 'add' | 'remove' | 'context';
  /** Line content (without the prefix) */
  content: string;
  /** Original line number (null for additions) */
  oldLineNumber: number | null;
  /** New line number (null for removals) */
  newLineNumber: number | null;
}

/**
 * A complete unified diff for a single file.
 */
export interface UnifiedDiff {
  /** Original file path */
  oldPath: string;
  /** New file path */
  newPath: string;
  /** Old file header (e.g., timestamp) */
  oldHeader?: string;
  /** New file header */
  newHeader?: string;
  /** Hunks in the diff */
  hunks: DiffHunk[];
  /** Whether the old file is /dev/null (new file) */
  isNewFile: boolean;
  /** Whether the new file is /dev/null (deleted file) */
  isDeletedFile: boolean;
}

/**
 * Result of applying a diff.
 */
export interface ApplyResult {
  /** Whether the patch applied successfully */
  success: boolean;
  /** Resulting content (if successful) */
  content?: string;
  /** Error message (if failed) */
  error?: string;
  /** Number of hunks applied */
  hunksApplied: number;
  /** Number of hunks that failed */
  hunksFailed: number;
  /** Details of failed hunks */
  failedHunks?: Array<{
    hunk: number;
    reason: string;
  }>;
}

// =============================================================================
// PARSING
// =============================================================================

/**
 * Parse a unified diff string into structured format.
 */
export function parseUnifiedDiff(diffText: string): UnifiedDiff[] {
  const diffs: UnifiedDiff[] = [];
  const lines = diffText.split('\n');
  let i = 0;

  while (i < lines.length) {
    // Look for diff header
    if (lines[i].startsWith('--- ')) {
      const diff = parseFileDiff(lines, i);
      if (diff) {
        diffs.push(diff.diff);
        i = diff.nextIndex;
      } else {
        i++;
      }
    } else if (lines[i].startsWith('diff --git')) {
      // Git diff format - skip to actual content
      i++;
    } else {
      i++;
    }
  }

  return diffs;
}

/**
 * Parse a single file diff starting at the given index.
 */
function parseFileDiff(
  lines: string[],
  startIndex: number,
): { diff: UnifiedDiff; nextIndex: number } | null {
  let i = startIndex;

  // Parse --- line
  if (!lines[i].startsWith('--- ')) return null;
  const oldLine = lines[i];
  const oldMatch = oldLine.match(/^--- (a\/)?(.+?)(\t.+)?$/);
  if (!oldMatch) return null;
  const oldPath = oldMatch[2];
  const oldHeader = oldMatch[3]?.trim();
  i++;

  // Parse +++ line
  if (!lines[i] || !lines[i].startsWith('+++ ')) return null;
  const newLine = lines[i];
  const newMatch = newLine.match(/^\+\+\+ (b\/)?(.+?)(\t.+)?$/);
  if (!newMatch) return null;
  const newPath = newMatch[2];
  const newHeader = newMatch[3]?.trim();
  i++;

  const diff: UnifiedDiff = {
    oldPath,
    newPath,
    oldHeader,
    newHeader,
    hunks: [],
    isNewFile: oldPath === '/dev/null',
    isDeletedFile: newPath === '/dev/null',
  };

  // Parse hunks
  while (i < lines.length) {
    if (lines[i].startsWith('@@ ')) {
      const hunkResult = parseHunk(lines, i);
      if (hunkResult) {
        diff.hunks.push(hunkResult.hunk);
        i = hunkResult.nextIndex;
      } else {
        i++;
      }
    } else if (lines[i].startsWith('--- ') || lines[i].startsWith('diff --git')) {
      // Next file
      break;
    } else {
      i++;
    }
  }

  return { diff, nextIndex: i };
}

/**
 * Parse a single hunk starting at the given index.
 */
function parseHunk(
  lines: string[],
  startIndex: number,
): { hunk: DiffHunk; nextIndex: number } | null {
  const headerLine = lines[startIndex];
  const match = headerLine.match(/^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/);
  if (!match) return null;

  const hunk: DiffHunk = {
    oldStart: parseInt(match[1], 10),
    oldCount: match[2] ? parseInt(match[2], 10) : 1,
    newStart: parseInt(match[3], 10),
    newCount: match[4] ? parseInt(match[4], 10) : 1,
    lines: [],
  };

  let i = startIndex + 1;
  let oldLine = hunk.oldStart;
  let newLine = hunk.newStart;

  while (i < lines.length) {
    const line = lines[i];

    // End of hunk
    if (line.startsWith('@@ ') || line.startsWith('--- ') || line.startsWith('diff --git')) {
      break;
    }

    if (line.startsWith('+')) {
      hunk.lines.push({
        type: 'add',
        content: line.slice(1),
        oldLineNumber: null,
        newLineNumber: newLine++,
      });
    } else if (line.startsWith('-')) {
      hunk.lines.push({
        type: 'remove',
        content: line.slice(1),
        oldLineNumber: oldLine++,
        newLineNumber: null,
      });
    } else if (line.startsWith(' ') || line === '') {
      hunk.lines.push({
        type: 'context',
        content: line.slice(1),
        oldLineNumber: oldLine++,
        newLineNumber: newLine++,
      });
    } else if (line.startsWith('\\')) {
      // "No newline at end of file" marker - skip
    } else {
      // Unknown line format, treat as context
      hunk.lines.push({
        type: 'context',
        content: line,
        oldLineNumber: oldLine++,
        newLineNumber: newLine++,
      });
    }

    i++;
  }

  return { hunk, nextIndex: i };
}

// =============================================================================
// APPLYING
// =============================================================================

/**
 * Apply a unified diff to original content.
 */
export function applyDiff(originalContent: string, diff: UnifiedDiff): ApplyResult {
  // Handle new file
  if (diff.isNewFile) {
    const newContent = diff.hunks
      .flatMap((h) => h.lines.filter((l) => l.type === 'add').map((l) => l.content))
      .join('\n');
    return {
      success: true,
      content: newContent,
      hunksApplied: diff.hunks.length,
      hunksFailed: 0,
    };
  }

  // Handle deleted file
  if (diff.isDeletedFile) {
    return {
      success: true,
      content: '',
      hunksApplied: diff.hunks.length,
      hunksFailed: 0,
    };
  }

  // Apply hunks to existing content
  const lines = originalContent.split('\n');
  let offset = 0;
  let hunksApplied = 0;
  let hunksFailed = 0;
  const failedHunks: Array<{ hunk: number; reason: string }> = [];

  for (let hunkIndex = 0; hunkIndex < diff.hunks.length; hunkIndex++) {
    const hunk = diff.hunks[hunkIndex];
    const result = applyHunk(lines, hunk, offset);

    if (result.success) {
      offset = result.newOffset;
      hunksApplied++;
    } else {
      hunksFailed++;
      failedHunks.push({ hunk: hunkIndex + 1, reason: result.error! });
    }
  }

  return {
    success: hunksFailed === 0,
    content: lines.join('\n'),
    hunksApplied,
    hunksFailed,
    failedHunks: failedHunks.length > 0 ? failedHunks : undefined,
  };
}

/**
 * Apply a single hunk to the lines array.
 */
function applyHunk(
  lines: string[],
  hunk: DiffHunk,
  offset: number,
): { success: boolean; newOffset: number; error?: string } {
  const startLine = hunk.oldStart - 1 + offset; // Convert to 0-indexed

  // Verify context matches
  let lineIndex = startLine;
  for (const diffLine of hunk.lines) {
    if (diffLine.type === 'context' || diffLine.type === 'remove') {
      if (lineIndex >= lines.length) {
        return {
          success: false,
          newOffset: offset,
          error: `Line ${lineIndex + 1} out of bounds`,
        };
      }
      if (lines[lineIndex] !== diffLine.content) {
        return {
          success: false,
          newOffset: offset,
          error: `Context mismatch at line ${lineIndex + 1}: expected "${diffLine.content}", got "${lines[lineIndex]}"`,
        };
      }
      lineIndex++;
    }
  }

  // Apply changes
  const toRemove: number[] = [];
  const toAdd: Array<{ index: number; content: string }> = [];

  lineIndex = startLine;
  for (const diffLine of hunk.lines) {
    if (diffLine.type === 'remove') {
      toRemove.push(lineIndex);
      lineIndex++;
    } else if (diffLine.type === 'add') {
      toAdd.push({ index: lineIndex, content: diffLine.content });
    } else if (diffLine.type === 'context') {
      lineIndex++;
    }
  }

  // Remove lines (in reverse order to preserve indices)
  toRemove.sort((a, b) => b - a);
  for (const idx of toRemove) {
    lines.splice(idx, 1);
  }

  // Add lines
  // Adjust indices for removed lines
  const removeOffset = toRemove.filter((r) => r < startLine).length;
  for (const add of toAdd) {
    const adjustedIndex = add.index - removeOffset;
    lines.splice(adjustedIndex, 0, add.content);
  }

  // Calculate new offset
  const newOffset = offset + (toAdd.length - toRemove.length);

  return { success: true, newOffset };
}

// =============================================================================
// GENERATING
// =============================================================================

/**
 * Generate a unified diff between two strings.
 */
export function generateDiff(
  oldContent: string,
  newContent: string,
  oldPath = 'a/file',
  newPath = 'b/file',
  contextLines = 3,
): string {
  const oldLines = oldContent.split('\n');
  const newLines = newContent.split('\n');

  // Use longest common subsequence algorithm
  const lcs = computeLCS(oldLines, newLines);
  const hunks = generateHunks(oldLines, newLines, lcs, contextLines);

  if (hunks.length === 0) {
    return ''; // No differences
  }

  const output: string[] = [`--- ${oldPath}`, `+++ ${newPath}`];

  for (const hunk of hunks) {
    const header = `@@ -${hunk.oldStart},${hunk.oldCount} +${hunk.newStart},${hunk.newCount} @@`;
    output.push(header);

    for (const line of hunk.lines) {
      const prefix = line.type === 'add' ? '+' : line.type === 'remove' ? '-' : ' ';
      output.push(prefix + line.content);
    }
  }

  return output.join('\n');
}

/**
 * Compute longest common subsequence.
 */
function computeLCS(a: string[], b: string[]): Array<[number, number]> {
  const m = a.length;
  const n = b.length;
  const dp: number[][] = Array(m + 1)
    .fill(null)
    .map(() => Array(n + 1).fill(0));

  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      if (a[i - 1] === b[j - 1]) {
        dp[i][j] = dp[i - 1][j - 1] + 1;
      } else {
        dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1]);
      }
    }
  }

  // Backtrack to find LCS
  const lcs: Array<[number, number]> = [];
  let i = m,
    j = n;
  while (i > 0 && j > 0) {
    if (a[i - 1] === b[j - 1]) {
      lcs.unshift([i - 1, j - 1]);
      i--;
      j--;
    } else if (dp[i - 1][j] > dp[i][j - 1]) {
      i--;
    } else {
      j--;
    }
  }

  return lcs;
}

/**
 * Generate hunks from LCS.
 */
function generateHunks(
  oldLines: string[],
  newLines: string[],
  lcs: Array<[number, number]>,
  contextLines: number,
): DiffHunk[] {
  const changes: Array<{
    type: 'same' | 'remove' | 'add';
    oldIdx: number;
    newIdx: number;
    content: string;
  }> = [];

  let oldIdx = 0;
  let newIdx = 0;
  let lcsIdx = 0;

  while (oldIdx < oldLines.length || newIdx < newLines.length) {
    if (lcsIdx < lcs.length && oldIdx === lcs[lcsIdx][0] && newIdx === lcs[lcsIdx][1]) {
      changes.push({ type: 'same', oldIdx, newIdx, content: oldLines[oldIdx] });
      oldIdx++;
      newIdx++;
      lcsIdx++;
    } else if (oldIdx < oldLines.length && (lcsIdx >= lcs.length || oldIdx < lcs[lcsIdx][0])) {
      changes.push({ type: 'remove', oldIdx, newIdx: -1, content: oldLines[oldIdx] });
      oldIdx++;
    } else if (newIdx < newLines.length && (lcsIdx >= lcs.length || newIdx < lcs[lcsIdx][1])) {
      changes.push({ type: 'add', oldIdx: -1, newIdx, content: newLines[newIdx] });
      newIdx++;
    }
  }

  // Group changes into hunks
  const hunks: DiffHunk[] = [];
  let hunkStart = -1;
  let hunkEnd = -1;

  for (let i = 0; i < changes.length; i++) {
    if (changes[i].type !== 'same') {
      if (hunkStart === -1) {
        hunkStart = Math.max(0, i - contextLines);
      }
      hunkEnd = Math.min(changes.length - 1, i + contextLines);
    } else if (hunkStart !== -1 && i > hunkEnd) {
      // Emit current hunk
      hunks.push(createHunk(changes, hunkStart, hunkEnd));
      hunkStart = -1;
      hunkEnd = -1;
    }
  }

  // Emit final hunk
  if (hunkStart !== -1) {
    hunks.push(createHunk(changes, hunkStart, hunkEnd));
  }

  return hunks;
}

/**
 * Create a hunk from a range of changes.
 */
function createHunk(
  changes: Array<{
    type: 'same' | 'remove' | 'add';
    oldIdx: number;
    newIdx: number;
    content: string;
  }>,
  start: number,
  end: number,
): DiffHunk {
  const lines: DiffLine[] = [];
  let oldStart = -1;
  let newStart = -1;
  let oldCount = 0;
  let newCount = 0;

  for (let i = start; i <= end; i++) {
    const change = changes[i];

    if (change.type === 'same') {
      if (oldStart === -1) oldStart = change.oldIdx + 1;
      if (newStart === -1) newStart = change.newIdx + 1;
      lines.push({
        type: 'context',
        content: change.content,
        oldLineNumber: change.oldIdx + 1,
        newLineNumber: change.newIdx + 1,
      });
      oldCount++;
      newCount++;
    } else if (change.type === 'remove') {
      if (oldStart === -1) oldStart = change.oldIdx + 1;
      lines.push({
        type: 'remove',
        content: change.content,
        oldLineNumber: change.oldIdx + 1,
        newLineNumber: null,
      });
      oldCount++;
    } else if (change.type === 'add') {
      if (newStart === -1) newStart = change.newIdx + 1;
      lines.push({
        type: 'add',
        content: change.content,
        oldLineNumber: null,
        newLineNumber: change.newIdx + 1,
      });
      newCount++;
    }
  }

  return {
    oldStart: oldStart === -1 ? 1 : oldStart,
    oldCount,
    newStart: newStart === -1 ? 1 : newStart,
    newCount,
    lines,
  };
}

// =============================================================================
// UTILITIES
// =============================================================================

/**
 * Get statistics about a diff.
 */
export function getDiffStats(diff: UnifiedDiff): {
  additions: number;
  deletions: number;
  files: number;
  hunks: number;
} {
  let additions = 0;
  let deletions = 0;

  for (const hunk of diff.hunks) {
    for (const line of hunk.lines) {
      if (line.type === 'add') additions++;
      else if (line.type === 'remove') deletions++;
    }
  }

  return {
    additions,
    deletions,
    files: 1,
    hunks: diff.hunks.length,
  };
}

/**
 * Format a diff for display with colors (ANSI escape codes).
 */
export function formatDiffColored(diff: UnifiedDiff): string {
  const RED = '\x1b[31m';
  const GREEN = '\x1b[32m';
  const CYAN = '\x1b[36m';
  const RESET = '\x1b[0m';

  const output: string[] = [
    `${CYAN}--- ${diff.oldPath}${RESET}`,
    `${CYAN}+++ ${diff.newPath}${RESET}`,
  ];

  for (const hunk of diff.hunks) {
    output.push(
      `${CYAN}@@ -${hunk.oldStart},${hunk.oldCount} +${hunk.newStart},${hunk.newCount} @@${RESET}`,
    );

    for (const line of hunk.lines) {
      if (line.type === 'add') {
        output.push(`${GREEN}+${line.content}${RESET}`);
      } else if (line.type === 'remove') {
        output.push(`${RED}-${line.content}${RESET}`);
      } else {
        output.push(` ${line.content}`);
      }
    }
  }

  return output.join('\n');
}
