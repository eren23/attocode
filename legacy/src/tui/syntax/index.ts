/**
 * Syntax Highlighting Module
 *
 * Custom minimal lexer for syntax highlighting in diffs and code blocks.
 * Zero external dependencies.
 */

// Export lexer API
export {
  type Token,
  type TokenType,
  type Tokenizer,
  tokenize,
  detectLanguage,
  getTokenColor,
  TOKEN_COLOR_MAP,
  registerTokenizer,
  getTokenizer,
} from './lexer.js';

// Register language tokenizers (side effect imports)
import './languages/javascript.js';
import './languages/python.js';
import './languages/json.js';
import './languages/bash.js';
