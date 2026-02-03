/**
 * Bash/Shell Tokenizer
 *
 * Handles bash, sh, zsh syntax highlighting.
 * Produces tokens for: keywords, strings, comments, variables, operators.
 */

import { type Token, type TokenType, registerTokenizer } from '../lexer.js';

// =============================================================================
// PATTERNS
// =============================================================================

const KEYWORDS = new Set([
  // Control flow
  'if', 'then', 'else', 'elif', 'fi',
  'case', 'esac', 'in',
  'for', 'while', 'until', 'do', 'done',
  'select',
  // Functions
  'function',
  // Builtins
  'break', 'continue', 'return', 'exit',
  'source', 'export', 'local', 'readonly', 'unset',
  'eval', 'exec', 'shift', 'trap', 'wait',
  'true', 'false',
]);

const COMMANDS = new Set([
  // Common commands
  'echo', 'printf', 'read', 'cd', 'pwd', 'ls', 'cp', 'mv', 'rm', 'mkdir', 'rmdir',
  'cat', 'head', 'tail', 'less', 'more', 'grep', 'sed', 'awk', 'sort', 'uniq',
  'find', 'xargs', 'wc', 'cut', 'tr', 'tee', 'diff', 'patch',
  'chmod', 'chown', 'chgrp', 'touch', 'ln', 'file', 'stat',
  'ps', 'kill', 'top', 'bg', 'fg', 'jobs', 'nohup',
  'curl', 'wget', 'ssh', 'scp', 'rsync',
  'git', 'npm', 'node', 'python', 'pip', 'make', 'docker',
  'sudo', 'su', 'which', 'whereis', 'type', 'alias', 'set',
  'test', '[', '[[',
]);

const OPERATORS = /^(?:&&|\|\||;;|<<-?|>>|[|&;<>])/;
const VARIABLE = /^\$(?:[a-zA-Z_][a-zA-Z0-9_]*|\{[^}]+\}|[0-9@#?$!*-])/;
const NUMBER = /^(?:0[xX][0-9a-fA-F]+|0[0-7]+|[0-9]+)/;
const IDENTIFIER = /^[a-zA-Z_][a-zA-Z0-9_]*/;
const WHITESPACE = /^[ \t]+/;

// =============================================================================
// TOKENIZER
// =============================================================================

function tokenizeBash(code: string): Token[] {
  const tokens: Token[] = [];
  let pos = 0;
  let lineStart = true;

  while (pos < code.length) {
    const remaining = code.slice(pos);
    let matched = false;

    // Comment
    if (remaining[0] === '#' && (lineStart || /^[ \t]$/.test(code[pos - 1] ?? ''))) {
      const endOfLine = remaining.indexOf('\n');
      const commentEnd = endOfLine === -1 ? remaining.length : endOfLine;
      tokens.push({ type: 'comment', content: remaining.slice(0, commentEnd) });
      pos += commentEnd;
      matched = true;
    }
    // Heredoc (simplified - just match the delimiter)
    else if (/^<<-?'?(\w+)'?/.test(remaining)) {
      const match = remaining.match(/^<<-?'?(\w+)'?/)!;
      tokens.push({ type: 'operator', content: match[0] });
      pos += match[0].length;
      matched = true;
    }
    // Double-quoted string (allows variable interpolation)
    else if (remaining[0] === '"') {
      const result = matchDoubleQuotedString(remaining);
      tokens.push(...result.tokens);
      pos += result.length;
      matched = true;
    }
    // Single-quoted string (no interpolation)
    else if (remaining[0] === "'") {
      let end = 1;
      while (end < remaining.length && remaining[end] !== "'") {
        end++;
      }
      if (end < remaining.length) end++; // Include closing quote
      tokens.push({ type: 'string', content: remaining.slice(0, end) });
      pos += end;
      matched = true;
    }
    // ANSI-C quoted string: $'...'
    else if (remaining.startsWith("$'")) {
      let end = 2;
      while (end < remaining.length) {
        if (remaining[end] === '\\' && end + 1 < remaining.length) {
          end += 2;
        } else if (remaining[end] === "'") {
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
    // Variable
    else if (VARIABLE.test(remaining)) {
      const match = remaining.match(VARIABLE)!;
      tokens.push({ type: 'number', content: match[0] }); // Use 'number' for variables (orange)
      pos += match[0].length;
      matched = true;
    }
    // Command substitution: $(...)
    else if (remaining.startsWith('$(')) {
      tokens.push({ type: 'operator', content: '$(' });
      pos += 2;
      matched = true;
    }
    // Backtick command substitution
    else if (remaining[0] === '`') {
      let end = 1;
      while (end < remaining.length && remaining[end] !== '`') {
        if (remaining[end] === '\\' && end + 1 < remaining.length) {
          end += 2;
        } else {
          end++;
        }
      }
      if (end < remaining.length) end++;
      tokens.push({ type: 'string', content: remaining.slice(0, end) });
      pos += end;
      matched = true;
    }
    // Number
    else if (NUMBER.test(remaining) && (lineStart || /[^a-zA-Z_]/.test(code[pos - 1] ?? ''))) {
      const match = remaining.match(NUMBER)!;
      tokens.push({ type: 'number', content: match[0] });
      pos += match[0].length;
      matched = true;
    }
    // Identifier / Keyword / Command
    else if (IDENTIFIER.test(remaining)) {
      const match = remaining.match(IDENTIFIER)!;
      const word = match[0];

      // Determine token type
      let type: TokenType;
      if (KEYWORDS.has(word)) {
        type = 'keyword';
      } else if (lineStart && COMMANDS.has(word)) {
        type = 'function';
      } else if (COMMANDS.has(word)) {
        type = 'function';
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
      lineStart = false;
      matched = true;
    }
    // Newline
    else if (remaining[0] === '\n') {
      tokens.push({ type: 'plain', content: '\n' });
      pos++;
      lineStart = true;
      matched = true;
    }
    // Punctuation
    else if (/^[{}[\]();=]/.test(remaining)) {
      tokens.push({ type: 'plain', content: remaining[0] });
      pos++;
      matched = true;
    }

    // Fallback
    if (!matched) {
      tokens.push({ type: 'plain', content: remaining[0] });
      pos++;
    }

    // Track line start
    if (remaining[0] !== ' ' && remaining[0] !== '\t' && remaining[0] !== '\n') {
      lineStart = false;
    }
  }

  return mergeAdjacentTokens(tokens);
}

// =============================================================================
// HELPERS
// =============================================================================

/**
 * Match a double-quoted string with variable interpolation.
 */
function matchDoubleQuotedString(code: string): { tokens: Token[]; length: number } {
  const tokens: Token[] = [];
  let pos = 1; // Skip opening quote
  let stringStart = 0;

  tokens.push({ type: 'string', content: '"' });

  while (pos < code.length) {
    // Escaped character
    if (code[pos] === '\\' && pos + 1 < code.length) {
      pos += 2;
      continue;
    }
    // Variable
    if (code[pos] === '$') {
      // Push string content before variable
      if (pos > stringStart + 1) {
        tokens.push({ type: 'string', content: code.slice(stringStart + 1, pos) });
      }

      // Match variable
      const remaining = code.slice(pos);
      const varMatch = remaining.match(VARIABLE);
      if (varMatch) {
        tokens.push({ type: 'number', content: varMatch[0] });
        pos += varMatch[0].length;
        stringStart = pos - 1;
        continue;
      }
      // $(command)
      if (remaining.startsWith('$(')) {
        let depth = 1;
        let end = 2;
        while (end < remaining.length && depth > 0) {
          if (remaining[end] === '(') depth++;
          else if (remaining[end] === ')') depth--;
          end++;
        }
        tokens.push({ type: 'operator', content: remaining.slice(0, end) });
        pos += end;
        stringStart = pos - 1;
        continue;
      }
    }
    // Closing quote
    if (code[pos] === '"') {
      if (pos > stringStart + 1) {
        tokens.push({ type: 'string', content: code.slice(stringStart + 1, pos) });
      }
      tokens.push({ type: 'string', content: '"' });
      return { tokens, length: pos + 1 };
    }
    pos++;
  }

  // Unterminated string
  if (pos > stringStart + 1) {
    tokens.push({ type: 'string', content: code.slice(stringStart + 1, pos) });
  }
  return { tokens, length: pos };
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

registerTokenizer('bash', tokenizeBash);
registerTokenizer('sh', tokenizeBash);
registerTokenizer('shell', tokenizeBash);
registerTokenizer('zsh', tokenizeBash);
