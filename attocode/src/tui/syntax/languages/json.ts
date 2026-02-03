/**
 * JSON Tokenizer
 *
 * Handles JSON syntax highlighting.
 * Produces tokens for: keywords (true/false/null), strings, numbers.
 */

import { type Token, registerTokenizer } from '../lexer.js';

// =============================================================================
// PATTERNS
// =============================================================================

const NUMBER = /^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/;
const WHITESPACE = /^[ \t\n\r]+/;

// =============================================================================
// TOKENIZER
// =============================================================================

function tokenizeJSON(code: string): Token[] {
  const tokens: Token[] = [];
  let pos = 0;

  while (pos < code.length) {
    const remaining = code.slice(pos);
    let matched = false;

    // Whitespace
    if (WHITESPACE.test(remaining)) {
      const match = remaining.match(WHITESPACE)!;
      tokens.push({ type: 'plain', content: match[0] });
      pos += match[0].length;
      matched = true;
    }
    // String (property name or value)
    else if (remaining[0] === '"') {
      let end = 1;
      while (end < remaining.length) {
        if (remaining[end] === '\\' && end + 1 < remaining.length) {
          end += 2; // Skip escaped character
        } else if (remaining[end] === '"') {
          end++;
          break;
        } else {
          end++;
        }
      }
      tokens.push({ type: 'string', content: remaining.slice(0, end) });
      pos += end;
      matched = true;
    }
    // Keywords: true, false, null
    else if (remaining.startsWith('true')) {
      tokens.push({ type: 'keyword', content: 'true' });
      pos += 4;
      matched = true;
    }
    else if (remaining.startsWith('false')) {
      tokens.push({ type: 'keyword', content: 'false' });
      pos += 5;
      matched = true;
    }
    else if (remaining.startsWith('null')) {
      tokens.push({ type: 'keyword', content: 'null' });
      pos += 4;
      matched = true;
    }
    // Number
    else if (NUMBER.test(remaining)) {
      const match = remaining.match(NUMBER)!;
      tokens.push({ type: 'number', content: match[0] });
      pos += match[0].length;
      matched = true;
    }
    // Punctuation: { } [ ] : ,
    else if (/^[{}\[\]:,]/.test(remaining)) {
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

registerTokenizer('json', tokenizeJSON);
