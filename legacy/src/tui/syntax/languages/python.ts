/**
 * Python Tokenizer
 *
 * Handles Python syntax highlighting.
 * Produces tokens for: keywords, strings, comments, numbers, functions, types, operators, decorators.
 */

import { type Token, type TokenType, registerTokenizer } from '../lexer.js';

// =============================================================================
// PATTERNS
// =============================================================================

const KEYWORDS = new Set([
  // Statements
  'if',
  'elif',
  'else',
  'for',
  'while',
  'break',
  'continue',
  'pass',
  'try',
  'except',
  'finally',
  'raise',
  'with',
  'as',
  'assert',
  'return',
  'yield',
  'del',
  // Declarations
  'def',
  'class',
  'lambda',
  'global',
  'nonlocal',
  // Imports
  'import',
  'from',
  // Async
  'async',
  'await',
  // Operators
  'and',
  'or',
  'not',
  'in',
  'is',
  // Values
  'True',
  'False',
  'None',
  // Match (Python 3.10+)
  'match',
  'case',
]);

const BUILTINS = new Set([
  'print',
  'len',
  'range',
  'str',
  'int',
  'float',
  'bool',
  'list',
  'dict',
  'set',
  'tuple',
  'type',
  'isinstance',
  'issubclass',
  'hasattr',
  'getattr',
  'setattr',
  'open',
  'input',
  'map',
  'filter',
  'zip',
  'enumerate',
  'sorted',
  'reversed',
  'min',
  'max',
  'sum',
  'abs',
  'round',
  'any',
  'all',
  'super',
  'property',
  'staticmethod',
  'classmethod',
  'object',
  'Exception',
  'ValueError',
  'TypeError',
  'KeyError',
  'IndexError',
  'RuntimeError',
  'StopIteration',
]);

const OPERATORS = /^(?:[+\-*/%@&|^~<>=!]+|:=|->)/;
const NUMBER =
  /^(?:0[xX][0-9a-fA-F_]+|0[oO][0-7_]+|0[bB][01_]+|(?:\d[\d_]*\.?[\d_]*|\.\d[\d_]*)(?:[eE][+-]?\d[\d_]*)?[jJ]?)/;
const IDENTIFIER = /^[a-zA-Z_][a-zA-Z0-9_]*/;
const WHITESPACE = /^[ \t]+/;

// =============================================================================
// TOKENIZER
// =============================================================================

function tokenizePython(code: string): Token[] {
  const tokens: Token[] = [];
  let pos = 0;

  while (pos < code.length) {
    const remaining = code.slice(pos);
    let matched = false;

    // Comment
    if (remaining[0] === '#') {
      const endOfLine = remaining.indexOf('\n');
      const commentEnd = endOfLine === -1 ? remaining.length : endOfLine;
      tokens.push({ type: 'comment', content: remaining.slice(0, commentEnd) });
      pos += commentEnd;
      matched = true;
    }
    // Triple-quoted string (docstring)
    else if (remaining.startsWith('"""') || remaining.startsWith("'''")) {
      const quote = remaining.slice(0, 3);
      const endQuote = remaining.indexOf(quote, 3);
      const stringEnd = endQuote === -1 ? remaining.length : endQuote + 3;
      tokens.push({ type: 'string', content: remaining.slice(0, stringEnd) });
      pos += stringEnd;
      matched = true;
    }
    // F-string (simplified handling)
    else if (/^[fFrRbBuU]{0,2}["']/.test(remaining)) {
      const result = matchPythonString(remaining);
      tokens.push({ type: 'string', content: remaining.slice(0, result.length) });
      pos += result.length;
      matched = true;
    }
    // Regular string
    else if (remaining[0] === '"' || remaining[0] === "'") {
      const result = matchPythonString(remaining);
      tokens.push({ type: 'string', content: remaining.slice(0, result.length) });
      pos += result.length;
      matched = true;
    }
    // Decorator
    else if (remaining[0] === '@') {
      const match = remaining.slice(1).match(IDENTIFIER);
      if (match) {
        tokens.push({ type: 'function', content: '@' + match[0] });
        pos += 1 + match[0].length;
        matched = true;
      }
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

      // Determine token type
      let type: TokenType;
      if (KEYWORDS.has(word)) {
        type = 'keyword';
      } else if (BUILTINS.has(word)) {
        type = 'function';
      } else if (followedByParen) {
        type = 'function';
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
    // Punctuation
    else if (/^[{}[\]();:,.]/.test(remaining)) {
      tokens.push({ type: 'plain', content: remaining[0] });
      pos++;
      matched = true;
    }

    // Fallback
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
 * Check if identifier is PascalCase (likely a class name).
 */
function isPascalCase(word: string): boolean {
  return /^[A-Z][a-zA-Z0-9]*$/.test(word);
}

/**
 * Match a Python string with optional prefix.
 */
function matchPythonString(code: string): { length: number } {
  let pos = 0;

  // Skip string prefix (r, f, b, u, or combinations)
  while (pos < code.length && /[fFrRbBuU]/.test(code[pos])) {
    pos++;
  }

  if (pos >= code.length) return { length: pos };

  const quote = code[pos];
  if (quote !== '"' && quote !== "'") return { length: pos };

  // Check for triple quote
  if (code.slice(pos, pos + 3) === quote.repeat(3)) {
    const tripleQuote = quote.repeat(3);
    const endQuote = code.indexOf(tripleQuote, pos + 3);
    return { length: endQuote === -1 ? code.length : endQuote + 3 };
  }

  // Single quote string
  pos++; // Skip opening quote
  while (pos < code.length) {
    if (code[pos] === '\\' && pos + 1 < code.length) {
      pos += 2; // Skip escaped character
    } else if (code[pos] === quote) {
      pos++;
      break;
    } else if (code[pos] === '\n') {
      // Unterminated string
      break;
    } else {
      pos++;
    }
  }

  return { length: pos };
}

/**
 * Merge adjacent tokens of the same type.
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

registerTokenizer('python', tokenizePython);
