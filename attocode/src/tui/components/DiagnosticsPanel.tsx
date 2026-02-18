/**
 * Diagnostics Panel Component
 *
 * Displays AST cache stats, TypeScript compilation state, and recent syntax errors.
 * Toggle with Alt+Y to show/hide.
 */

import { memo } from 'react';
import { Box, Text } from 'ink';
import type { ThemeColors } from '../types.js';
import type { TransparencyState } from '../transparency-aggregator.js';
import type { TypeCheckerState } from '../../integrations/safety/type-checker.js';

// =============================================================================
// TYPES
// =============================================================================

export interface DiagnosticsPanelProps {
  diagnostics: TransparencyState['diagnostics'];
  typeCheckerState: TypeCheckerState | null;
  astCacheStats: {
    fileCount: number;
    languages: Record<string, number>;
    totalParses: number;
    cacheHits: number;
  } | null;
  expanded: boolean;
  colors: ThemeColors;
}

// =============================================================================
// COMPONENT
// =============================================================================

export const DiagnosticsPanel = memo(function DiagnosticsPanel({
  diagnostics,
  typeCheckerState,
  astCacheStats,
  expanded,
  colors,
}: DiagnosticsPanelProps) {
  if (!expanded) return null;

  const tscResult = diagnostics.lastTscResult;

  // AST cache summary
  const astSummary = astCacheStats
    ? `${astCacheStats.fileCount} files (${astCacheStats.totalParses} parses, ${astCacheStats.cacheHits} hits)`
    : 'not available';

  const langBreakdown =
    astCacheStats && Object.keys(astCacheStats.languages).length > 0
      ? Object.entries(astCacheStats.languages)
          .map(([k, v]) => `${k}:${v}`)
          .join(' ')
      : '';

  // TSC status
  let tscStatus: string;
  let tscColor: string;
  if (!typeCheckerState?.tsconfigDir) {
    tscStatus = 'not configured (no tsconfig.json)';
    tscColor = colors.textMuted;
  } else if (!tscResult) {
    tscStatus = 'not run yet';
    tscColor = colors.textMuted;
  } else if (tscResult.success) {
    tscStatus = `clean (${tscResult.duration}ms)`;
    tscColor = '#98FB98';
  } else {
    tscStatus = `${tscResult.errorCount} error(s) (${tscResult.duration}ms)`;
    tscColor = colors.error;
  }

  const tsEdits = typeCheckerState?.tsEditsSinceLastCheck ?? 0;

  return (
    <Box
      flexDirection="column"
      marginBottom={1}
      borderStyle="single"
      borderColor={colors.border}
      paddingX={1}
    >
      <Box justifyContent="space-between">
        <Text color={colors.accent} bold>
          [d] Diagnostics (Alt+Y)
        </Text>
        <Text color={colors.textMuted} dimColor>
          {typeCheckerState?.tsconfigDir ? 'TypeScript project' : ''}
        </Text>
      </Box>

      <Box flexDirection="column" marginTop={1}>
        {/* AST Cache */}
        <Box gap={1}>
          <Text color={colors.textMuted}>AST Cache:</Text>
          <Text color={colors.text}>{astSummary}</Text>
        </Box>
        {langBreakdown && (
          <Box gap={1}>
            <Text color={colors.textMuted}> </Text>
            <Text color={colors.textMuted} dimColor>
              {langBreakdown}
            </Text>
          </Box>
        )}

        {/* Type Checker */}
        <Box gap={1}>
          <Text color={colors.textMuted}>Type Check:</Text>
          <Text color={tscColor}>
            {tscResult?.success ? '[ok]' : tscResult ? '[X]' : '[-]'} {tscStatus}
          </Text>
        </Box>
        {tsEdits > 0 && (
          <Box gap={1}>
            <Text color={colors.textMuted}> </Text>
            <Text color={colors.warning} dimColor>
              {tsEdits} TS edit(s) since last check
            </Text>
          </Box>
        )}

        {/* Recent Syntax Errors */}
        {diagnostics.recentSyntaxErrors.length > 0 && (
          <>
            <Box marginTop={1}>
              <Text color={colors.warning} bold>
                Recent Syntax Errors:
              </Text>
            </Box>
            {diagnostics.recentSyntaxErrors.slice(-5).map((err, i) => (
              <Box key={`${err.file}:${err.line}:${i}`} gap={1}>
                <Text color={colors.textMuted} dimColor>
                  {' '}
                </Text>
                <Text color={colors.error} wrap="truncate">
                  {err.file.split('/').pop()}:{err.line} — {err.message}
                </Text>
              </Box>
            ))}
          </>
        )}
      </Box>
    </Box>
  );
}, (prev, next) => {
  if (prev.expanded !== next.expanded) return false;
  if (prev.colors !== next.colors) return false;
  if (!prev.expanded && !next.expanded) return true;
  if (prev.diagnostics !== next.diagnostics) return false;
  if (prev.typeCheckerState !== next.typeCheckerState) return false;
  if (prev.astCacheStats !== next.astCacheStats) return false;
  return true;
});

export default DiagnosticsPanel;
