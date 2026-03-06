/**
 * SyntaxText Component
 *
 * Renders code with syntax highlighting using the theme's code colors.
 */

import React from 'react';
import { Text } from 'ink';
import { tokenize, detectLanguage, getTokenColor } from '../syntax/index.js';
import type { ThemeColors } from '../types.js';

// =============================================================================
// TYPES
// =============================================================================

export interface SyntaxTextProps {
  /** The code to highlight */
  code: string;
  /** Language for highlighting (overrides auto-detection) */
  language?: string;
  /** File path for auto-detection (used if language not specified) */
  filePath?: string;
  /** Theme colors for syntax highlighting */
  theme: ThemeColors;
}

// =============================================================================
// COMPONENT
// =============================================================================

/**
 * Renders code with syntax highlighting.
 *
 * Uses the theme's code colors (codeKeyword, codeString, etc.) for highlighting.
 * Language can be specified directly or auto-detected from file path.
 */
export function SyntaxText({
  code,
  language,
  filePath,
  theme,
}: SyntaxTextProps): React.ReactElement {
  // Determine language
  const detectedLang = language || (filePath ? detectLanguage(filePath) : null);

  // Tokenize code
  const tokens = detectedLang
    ? tokenize(code, detectedLang)
    : [{ type: 'plain' as const, content: code }];

  return (
    <>
      {tokens.map((token, i) => (
        <Text key={i} color={getTokenColor(token.type, theme)}>
          {token.content}
        </Text>
      ))}
    </>
  );
}

// =============================================================================
// MEMOIZED VERSION
// =============================================================================

/**
 * Memoized version of SyntaxText for use in lists.
 */
export const MemoizedSyntaxText = React.memo(SyntaxText);

// =============================================================================
// LINE-BY-LINE VERSION
// =============================================================================

export interface SyntaxLineProps {
  /** Single line of code to highlight */
  line: string;
  /** Language for highlighting */
  language?: string;
  /** File path for auto-detection */
  filePath?: string;
  /** Theme colors */
  theme: ThemeColors;
  /** Optional prefix (like line number or +/-) */
  prefix?: React.ReactNode;
}

/**
 * Renders a single line of code with syntax highlighting.
 * Useful for diff views where each line needs individual styling.
 */
export function SyntaxLine({
  line,
  language,
  filePath,
  theme,
  prefix,
}: SyntaxLineProps): React.ReactElement {
  return (
    <Text>
      {prefix}
      <SyntaxText code={line} language={language} filePath={filePath} theme={theme} />
    </Text>
  );
}

export const MemoizedSyntaxLine = React.memo(SyntaxLine);
