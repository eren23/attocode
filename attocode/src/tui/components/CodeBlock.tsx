/**
 * CodeBlock Component
 *
 * Renders code with syntax highlighting in the terminal.
 */

import React, { useMemo } from 'react';
import { Box, Text } from 'ink';
import type { Theme } from '../theme/index.js';

export interface CodeBlockProps {
  theme: Theme;
  code: string;
  language?: string;
  showLineNumbers?: boolean;
  highlightLines?: number[];
  maxHeight?: number;
  title?: string;
}

// Language keywords for basic syntax highlighting
const languageKeywords: Record<string, string[]> = {
  javascript: [
    'function', 'const', 'let', 'var', 'if', 'else', 'for', 'while', 'return',
    'import', 'export', 'from', 'class', 'extends', 'new', 'this', 'try',
    'catch', 'finally', 'async', 'await', 'true', 'false', 'null', 'undefined',
    'typeof', 'instanceof', 'default', 'throw', 'switch', 'case', 'break',
    'continue', 'do', 'in', 'of', 'yield', 'static', 'get', 'set',
  ],
  typescript: [
    'function', 'const', 'let', 'var', 'if', 'else', 'for', 'while', 'return',
    'import', 'export', 'from', 'class', 'extends', 'new', 'this', 'try',
    'catch', 'finally', 'async', 'await', 'true', 'false', 'null', 'undefined',
    'typeof', 'instanceof', 'interface', 'type', 'enum', 'as', 'implements',
    'private', 'public', 'protected', 'readonly', 'abstract', 'declare',
    'namespace', 'module', 'keyof', 'infer', 'never', 'unknown', 'any',
  ],
  python: [
    'def', 'class', 'if', 'elif', 'else', 'for', 'while', 'return', 'import',
    'from', 'as', 'try', 'except', 'finally', 'with', 'lambda', 'yield',
    'async', 'await', 'True', 'False', 'None', 'and', 'or', 'not', 'in', 'is',
    'raise', 'pass', 'break', 'continue', 'global', 'nonlocal', 'assert',
  ],
  go: [
    'func', 'package', 'import', 'var', 'const', 'type', 'struct', 'interface',
    'map', 'chan', 'if', 'else', 'for', 'range', 'switch', 'case', 'default',
    'return', 'break', 'continue', 'go', 'select', 'defer', 'nil', 'true', 'false',
  ],
  rust: [
    'fn', 'let', 'mut', 'const', 'if', 'else', 'match', 'for', 'while', 'loop',
    'return', 'use', 'mod', 'pub', 'struct', 'enum', 'impl', 'trait', 'self',
    'Self', 'where', 'async', 'await', 'move', 'ref', 'true', 'false', 'None',
    'Some', 'Ok', 'Err', 'unsafe', 'extern', 'crate', 'super', 'dyn', 'static',
  ],
  bash: [
    'if', 'then', 'else', 'elif', 'fi', 'for', 'while', 'do', 'done', 'case',
    'esac', 'function', 'return', 'exit', 'local', 'export', 'readonly',
    'declare', 'source', 'alias', 'unset', 'shift', 'true', 'false',
  ],
  json: [],
  yaml: [],
  markdown: [],
  sql: [
    'SELECT', 'FROM', 'WHERE', 'AND', 'OR', 'NOT', 'INSERT', 'INTO', 'VALUES',
    'UPDATE', 'SET', 'DELETE', 'CREATE', 'TABLE', 'DROP', 'ALTER', 'INDEX',
    'JOIN', 'LEFT', 'RIGHT', 'INNER', 'OUTER', 'ON', 'GROUP', 'BY', 'ORDER',
    'ASC', 'DESC', 'LIMIT', 'OFFSET', 'HAVING', 'UNION', 'AS', 'DISTINCT',
    'NULL', 'TRUE', 'FALSE', 'IN', 'LIKE', 'BETWEEN', 'IS', 'EXISTS',
  ],
};

// Normalize language name
function normalizeLanguage(lang?: string): string {
  if (!lang) return 'text';
  const l = lang.toLowerCase();
  if (l === 'js' || l === 'jsx') return 'javascript';
  if (l === 'ts' || l === 'tsx') return 'typescript';
  if (l === 'py') return 'python';
  if (l === 'sh' || l === 'shell' || l === 'zsh') return 'bash';
  if (l === 'yml') return 'yaml';
  if (l === 'md') return 'markdown';
  return l;
}

interface TokenizedPart {
  text: string;
  type: 'keyword' | 'string' | 'comment' | 'number' | 'function' | 'type' | 'text';
}

/**
 * Tokenize a line for syntax highlighting.
 */
function tokenizeLine(line: string, language: string): TokenizedPart[] {
  const keywords = languageKeywords[language] || [];
  const parts: TokenizedPart[] = [];

  // Simple tokenization - not a full parser but good enough for display
  let remaining = line;
  let pos = 0;

  while (remaining.length > 0) {
    // Check for comments
    const commentMatch = remaining.match(/^(\/\/.*|#.*|--.*)/);
    if (commentMatch) {
      parts.push({ text: commentMatch[0], type: 'comment' });
      remaining = remaining.slice(commentMatch[0].length);
      continue;
    }

    // Check for strings
    const stringMatch = remaining.match(/^(["'`])((?:\\\1|(?:(?!\1)).)*)\1/);
    if (stringMatch) {
      parts.push({ text: stringMatch[0], type: 'string' });
      remaining = remaining.slice(stringMatch[0].length);
      continue;
    }

    // Check for numbers
    const numberMatch = remaining.match(/^\b(\d+\.?\d*)\b/);
    if (numberMatch) {
      parts.push({ text: numberMatch[0], type: 'number' });
      remaining = remaining.slice(numberMatch[0].length);
      continue;
    }

    // Check for keywords and identifiers
    const wordMatch = remaining.match(/^([a-zA-Z_]\w*)/);
    if (wordMatch) {
      const word = wordMatch[0];
      const isKeyword = keywords.includes(word) ||
        (language === 'sql' && keywords.includes(word.toUpperCase()));

      // Check if it's a function call (followed by parenthesis)
      const isFunction = remaining.slice(word.length).match(/^\s*\(/);

      // Check if it looks like a type (PascalCase in relevant languages)
      const isType = ['typescript', 'rust', 'go'].includes(language) &&
        /^[A-Z][a-zA-Z0-9]*$/.test(word) && !isKeyword;

      if (isKeyword) {
        parts.push({ text: word, type: 'keyword' });
      } else if (isFunction) {
        parts.push({ text: word, type: 'function' });
      } else if (isType) {
        parts.push({ text: word, type: 'type' });
      } else {
        parts.push({ text: word, type: 'text' });
      }
      remaining = remaining.slice(word.length);
      continue;
    }

    // Any other character
    parts.push({ text: remaining[0], type: 'text' });
    remaining = remaining.slice(1);
  }

  return parts;
}

/**
 * Highlighted line component.
 */
function HighlightedLine({
  theme,
  line,
  language,
  lineNumber,
  showLineNumber,
  highlighted,
}: {
  theme: Theme;
  line: string;
  language: string;
  lineNumber: number;
  showLineNumber: boolean;
  highlighted: boolean;
}) {
  const tokens = useMemo(() => tokenizeLine(line, language), [line, language]);

  const getTokenColor = (type: TokenizedPart['type']): string => {
    switch (type) {
      case 'keyword': return theme.colors.codeKeyword;
      case 'string': return theme.colors.codeString;
      case 'comment': return theme.colors.codeComment;
      case 'number': return theme.colors.codeNumber;
      case 'function': return theme.colors.codeFunction;
      case 'type': return theme.colors.codeType;
      default: return theme.colors.text;
    }
  };

  return (
    <Box>
      {showLineNumber && (
        <Text color={theme.colors.textMuted}>
          {lineNumber.toString().padStart(3, ' ')} |{' '}
        </Text>
      )}
      <Text backgroundColor={highlighted ? theme.colors.backgroundAlt : undefined}>
        {tokens.map((token, i) => (
          <Text key={i} color={getTokenColor(token.type)}>
            {token.text}
          </Text>
        ))}
      </Text>
    </Box>
  );
}

/**
 * Code block component with syntax highlighting.
 */
export function CodeBlock({
  theme,
  code,
  language,
  showLineNumbers = false,
  highlightLines = [],
  maxHeight,
  title,
}: CodeBlockProps) {
  const normalizedLang = normalizeLanguage(language);
  const lines = code.split('\n');

  // Limit lines if maxHeight specified
  const visibleLines = maxHeight ? lines.slice(0, maxHeight) : lines;
  const hasMore = maxHeight && lines.length > maxHeight;

  return (
    <Box
      flexDirection="column"
      marginY={1}
      borderStyle="single"
      borderColor={theme.colors.border}
      paddingX={1}
    >
      {/* Header with language label */}
      {(language || title) && (
        <Box marginBottom={1}>
          {title && (
            <Text bold color={theme.colors.text}>{title}</Text>
          )}
          {title && language && <Text color={theme.colors.textMuted}> </Text>}
          {language && (
            <Text color={theme.colors.accent}>[{language}]</Text>
          )}
        </Box>
      )}

      {/* Code lines */}
      <Box flexDirection="column">
        {visibleLines.map((line, index) => (
          <HighlightedLine
            key={index}
            theme={theme}
            line={line}
            language={normalizedLang}
            lineNumber={index + 1}
            showLineNumber={showLineNumbers}
            highlighted={highlightLines.includes(index + 1)}
          />
        ))}
      </Box>

      {/* Truncation indicator */}
      {hasMore && (
        <Box marginTop={1}>
          <Text color={theme.colors.textMuted}>
            ... {lines.length - visibleLines.length} more lines
          </Text>
        </Box>
      )}
    </Box>
  );
}

export default CodeBlock;
