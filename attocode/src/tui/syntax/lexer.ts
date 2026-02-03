/**
 * Syntax Lexer Module
 *
 * Custom minimal lexer for syntax highlighting in diffs.
 * Zero external dependencies - uses theme colors directly.
 */

import type { ThemeColors } from '../types.js';

// =============================================================================
// TOKEN TYPES
// =============================================================================

/**
 * Token types that map to existing ThemeColors.
 */
export type TokenType =
  | 'keyword'
  | 'string'
  | 'comment'
  | 'number'
  | 'function'
  | 'type'
  | 'operator'
  | 'plain';

/**
 * A token produced by the lexer.
 */
export interface Token {
  type: TokenType;
  content: string;
}

/**
 * Language-specific tokenizer function.
 */
export type Tokenizer = (code: string) => Token[];

// =============================================================================
// LANGUAGE REGISTRY
// =============================================================================

const tokenizers = new Map<string, Tokenizer>();

/**
 * Register a language tokenizer.
 */
export function registerTokenizer(language: string, tokenizer: Tokenizer): void {
  tokenizers.set(language.toLowerCase(), tokenizer);
}

/**
 * Get a tokenizer by language name.
 */
export function getTokenizer(language: string): Tokenizer | undefined {
  return tokenizers.get(language.toLowerCase());
}

// =============================================================================
// LANGUAGE DETECTION
// =============================================================================

const extensionMap: Record<string, string> = {
  // JavaScript/TypeScript
  js: 'javascript',
  jsx: 'javascript',
  ts: 'typescript',
  tsx: 'typescript',
  mjs: 'javascript',
  cjs: 'javascript',
  mts: 'typescript',
  cts: 'typescript',

  // Python
  py: 'python',
  pyw: 'python',
  pyi: 'python',

  // JSON
  json: 'json',
  jsonc: 'json',
  jsonl: 'json',

  // Shell
  sh: 'bash',
  bash: 'bash',
  zsh: 'bash',
  fish: 'bash',

  // Markdown
  md: 'markdown',
  markdown: 'markdown',

  // HTML/CSS
  html: 'html',
  htm: 'html',
  css: 'css',
  scss: 'css',
  sass: 'css',
  less: 'css',

  // Other
  yaml: 'yaml',
  yml: 'yaml',
  toml: 'toml',
  xml: 'xml',
  sql: 'sql',
  go: 'go',
  rs: 'rust',
  rb: 'ruby',
  php: 'php',
  java: 'java',
  c: 'c',
  cpp: 'cpp',
  h: 'c',
  hpp: 'cpp',
};

/**
 * Detect language from file extension.
 * Returns the normalized language name or null if unknown.
 */
export function detectLanguage(filePath: string): string | null {
  const ext = filePath.split('.').pop()?.toLowerCase();
  if (!ext) return null;
  return extensionMap[ext] ?? null;
}

// =============================================================================
// MAIN TOKENIZATION API
// =============================================================================

/**
 * Tokenize code using the appropriate language tokenizer.
 * Falls back to plain text if language is unknown.
 */
export function tokenize(code: string, language: string): Token[] {
  // Normalize language name
  const normalizedLang = language.toLowerCase();

  // TypeScript uses JavaScript tokenizer
  const effectiveLang = normalizedLang === 'typescript' ? 'javascript' : normalizedLang;

  const tokenizer = tokenizers.get(effectiveLang);

  if (!tokenizer) {
    // Fallback: return entire code as plain text
    return [{ type: 'plain', content: code }];
  }

  return tokenizer(code);
}

// =============================================================================
// THEME COLOR MAPPING
// =============================================================================

/**
 * Map token types to theme color keys.
 */
export const TOKEN_COLOR_MAP: Record<TokenType, keyof ThemeColors> = {
  keyword: 'codeKeyword',
  string: 'codeString',
  comment: 'codeComment',
  number: 'codeNumber',
  function: 'codeFunction',
  type: 'codeType',
  operator: 'textMuted',
  plain: 'text',
};

/**
 * Get the theme color for a token type.
 */
export function getTokenColor(tokenType: TokenType, theme: ThemeColors): string {
  const colorKey = TOKEN_COLOR_MAP[tokenType];
  return theme[colorKey];
}

// =============================================================================
// EXPORTS
// =============================================================================

export { tokenizers };
