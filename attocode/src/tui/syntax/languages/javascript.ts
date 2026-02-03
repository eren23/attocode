/**
 * JavaScript/TypeScript Tokenizer
 *
 * Handles JS, JSX, TS, TSX syntax highlighting.
 * Produces tokens for: keywords, strings, comments, numbers, functions, types, operators.
 */

import { type Token, type TokenType, registerTokenizer } from '../lexer.js';

// =============================================================================
// PATTERNS
// =============================================================================

const KEYWORDS = new Set([
  // Declarations
  'const', 'let', 'var', 'function', 'class', 'interface', 'type', 'enum', 'namespace',
  // Control flow
  'if', 'else', 'switch', 'case', 'default', 'break', 'continue',
  'for', 'while', 'do', 'in', 'of',
  'try', 'catch', 'finally', 'throw',
  'return', 'yield',
  // Modules
  'import', 'export', 'from', 'as', 'default',
  // Async
  'async', 'await',
  // OOP
  'new', 'this', 'super', 'extends', 'implements', 'static', 'get', 'set',
  'public', 'private', 'protected', 'readonly', 'abstract', 'override',
  // Operators
  'typeof', 'instanceof', 'delete', 'void',
  // Values
  'true', 'false', 'null', 'undefined', 'NaN', 'Infinity',
  // TypeScript
  'declare', 'module', 'keyof', 'infer', 'satisfies', 'is', 'asserts',
]);

const OPERATORS = /^(?:[+\-*/%&|^!~<>=?:]+|\.{3}|=>)/;
const NUMBER = /^(?:0[xX][0-9a-fA-F_]+|0[oO][0-7_]+|0[bB][01_]+|(?:\d[\d_]*\.?[\d_]*|\.\d[\d_]*)(?:[eE][+-]?\d[\d_]*)?n?)/;
const IDENTIFIER = /^[a-zA-Z_$][a-zA-Z0-9_$]*/;
const WHITESPACE = /^[ \t]+/;

// =============================================================================
// TOKENIZER
// =============================================================================

function tokenizeJavaScript(code: string): Token[] {
  const tokens: Token[] = [];
  let pos = 0;

  while (pos < code.length) {
    const remaining = code.slice(pos);
    let matched = false;

    // Single-line comment
    if (remaining.startsWith('//')) {
      const endOfLine = remaining.indexOf('\n');
      const commentEnd = endOfLine === -1 ? remaining.length : endOfLine;
      tokens.push({ type: 'comment', content: remaining.slice(0, commentEnd) });
      pos += commentEnd;
      matched = true;
    }
    // Multi-line comment
    else if (remaining.startsWith('/*')) {
      const endComment = remaining.indexOf('*/', 2);
      const commentEnd = endComment === -1 ? remaining.length : endComment + 2;
      tokens.push({ type: 'comment', content: remaining.slice(0, commentEnd) });
      pos += commentEnd;
      matched = true;
    }
    // Template literal
    else if (remaining[0] === '`') {
      const result = matchTemplateLiteral(remaining);
      tokens.push(...result.tokens);
      pos += result.length;
      matched = true;
    }
    // String (single or double quote)
    else if (remaining[0] === '"' || remaining[0] === "'") {
      const quote = remaining[0];
      let end = 1;
      while (end < remaining.length) {
        if (remaining[end] === '\\' && end + 1 < remaining.length) {
          end += 2; // Skip escaped character
        } else if (remaining[end] === quote) {
          end++;
          break;
        } else if (remaining[end] === '\n') {
          // Unterminated string
          break;
        } else {
          end++;
        }
      }
      tokens.push({ type: 'string', content: remaining.slice(0, end) });
      pos += end;
      matched = true;
    }
    // Number
    else if (NUMBER.test(remaining)) {
      const match = remaining.match(NUMBER)!;
      tokens.push({ type: 'number', content: match[0] });
      pos += match[0].length;
      matched = true;
    }
    // Identifier / Keyword / Function / Type
    else if (IDENTIFIER.test(remaining)) {
      const match = remaining.match(IDENTIFIER)!;
      const word = match[0];
      const afterWord = remaining.slice(word.length);

      // Check what follows the identifier
      const followedByParen = /^\s*\(/.test(afterWord);
      const followedByGeneric = /^\s*</.test(afterWord);

      // Determine token type
      let type: TokenType;
      if (KEYWORDS.has(word)) {
        type = 'keyword';
      } else if (followedByParen || followedByGeneric) {
        // Function call or generic type
        type = isPascalCase(word) ? 'type' : 'function';
      } else if (isPascalCase(word)) {
        type = 'type';
      } else {
        type = 'plain';
      }

      tokens.push({ type, content: word });
      pos += word.length;
      matched = true;
    }
    // Operators
    else if (OPERATORS.test(remaining)) {
      const match = remaining.match(OPERATORS)!;
      tokens.push({ type: 'operator', content: match[0] });
      pos += match[0].length;
      matched = true;
    }
    // Whitespace
    else if (WHITESPACE.test(remaining)) {
      const match = remaining.match(WHITESPACE)!;
      tokens.push({ type: 'plain', content: match[0] });
      pos += match[0].length;
      matched = true;
    }
    // Newline
    else if (remaining[0] === '\n') {
      tokens.push({ type: 'plain', content: '\n' });
      pos++;
      matched = true;
    }
    // Punctuation (braces, brackets, semicolons, etc.)
    else if (/^[{}[\]();,]/.test(remaining)) {
      tokens.push({ type: 'plain', content: remaining[0] });
      pos++;
      matched = true;
    }

    // Fallback: single character as plain
    if (!matched) {
      tokens.push({ type: 'plain', content: remaining[0] });
      pos++;
    }
  }

  return mergeAdjacentTokens(tokens);
}

// =============================================================================
// HELPERS
// =============================================================================

/**
 * Check if identifier is PascalCase (likely a type/class name).
 */
function isPascalCase(word: string): boolean {
  return /^[A-Z][a-zA-Z0-9]*$/.test(word);
}

/**
 * Match a template literal with embedded expressions.
 */
function matchTemplateLiteral(code: string): { tokens: Token[]; length: number } {
  const tokens: Token[] = [];
  let pos = 1; // Skip opening backtick
  let stringStart = 0;

  // Add opening backtick
  tokens.push({ type: 'string', content: '`' });

  while (pos < code.length) {
    // Escaped character
    if (code[pos] === '\\' && pos + 1 < code.length) {
      pos += 2;
      continue;
    }
    // Template expression: ${...}
    if (code[pos] === '$' && code[pos + 1] === '{') {
      // Push string content before expression
      if (pos > stringStart + 1) {
        tokens.push({ type: 'string', content: code.slice(stringStart + 1, pos) });
      }

      // Find matching closing brace
      let braceDepth = 1;
      let exprEnd = pos + 2;
      while (exprEnd < code.length && braceDepth > 0) {
        if (code[exprEnd] === '{') braceDepth++;
        else if (code[exprEnd] === '}') braceDepth--;
        exprEnd++;
      }

      // Tokenize the expression content
      const exprContent = code.slice(pos + 2, exprEnd - 1);
      tokens.push({ type: 'operator', content: '${' });
      tokens.push(...tokenizeJavaScript(exprContent));
      tokens.push({ type: 'operator', content: '}' });

      pos = exprEnd;
      stringStart = pos - 1;
      continue;
    }
    // Closing backtick
    if (code[pos] === '`') {
      if (pos > stringStart + 1) {
        tokens.push({ type: 'string', content: code.slice(stringStart + 1, pos) });
      }
      tokens.push({ type: 'string', content: '`' });
      return { tokens, length: pos + 1 };
    }
    pos++;
  }

  // Unterminated template literal
  if (pos > stringStart + 1) {
    tokens.push({ type: 'string', content: code.slice(stringStart + 1, pos) });
  }
  return { tokens, length: pos };
}

/**
 * Merge adjacent tokens of the same type for cleaner output.
 */
function mergeAdjacentTokens(tokens: Token[]): Token[] {
  if (tokens.length === 0) return tokens;

  const merged: Token[] = [];
  let current = tokens[0];

  for (let i = 1; i < tokens.length; i++) {
    if (tokens[i].type === current.type) {
      current = { type: current.type, content: current.content + tokens[i].content };
    } else {
      merged.push(current);
      current = tokens[i];
    }
  }
  merged.push(current);

  return merged;
}

// =============================================================================
// REGISTER
// =============================================================================

registerTokenizer('javascript', tokenizeJavaScript);
registerTokenizer('typescript', tokenizeJavaScript);
registerTokenizer('jsx', tokenizeJavaScript);
registerTokenizer('tsx', tokenizeJavaScript);
