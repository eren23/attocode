/**
 * Edit Validator (Phase 5.1)
 *
 * Post-edit syntax validation using tree-sitter AST parsing.
 * Catches broken edits before they hit runtime by detecting ERROR
 * nodes in the parsed syntax tree.
 *
 * Only validates files with AST support (TS/TSX/JS/JSX/Python).
 * Unsupported files always return valid (no-op).
 */

import * as path from 'path';
import { getParser, getCachedParse, type SyntaxNode } from '../context/codebase-ast.js';

// =============================================================================
// TYPES
// =============================================================================

export interface SyntaxError {
  line: number;
  column: number;
  message: string;
}

export interface ValidationResult {
  valid: boolean;
  errors: SyntaxError[];
}

// =============================================================================
// VALIDATION
// =============================================================================

/**
 * Walk the AST tree and collect all ERROR nodes.
 */
function collectErrors(node: SyntaxNode, errors: SyntaxError[], maxErrors: number = 10): void {
  if (errors.length >= maxErrors) return;

  if (node.type === 'ERROR') {
    const snippet = node.text.slice(0, 60).replace(/\n/g, '\\n');
    errors.push({
      line: node.startPosition.row + 1,
      column: node.startPosition.column + 1,
      message: `Syntax error near: ${snippet}`,
    });
    return; // Don't recurse into ERROR children
  }

  for (const child of node.namedChildren) {
    collectErrors(child, errors, maxErrors);
  }
}

/**
 * Validate syntax of file content using tree-sitter.
 * Returns { valid: true } for unsupported file types (no-op).
 */
export function validateSyntax(content: string, filePath: string): ValidationResult {
  const ext = path.extname(filePath).toLowerCase();
  const parser = getParser(ext);

  // Unsupported files always pass
  if (!parser) {
    return { valid: true, errors: [] };
  }

  try {
    // Use cached tree if available (file may have just been parsed during analyze)
    const cached = getCachedParse(filePath);
    const tree = cached?.tree ?? parser.parse(content);
    const errors: SyntaxError[] = [];
    collectErrors(tree.rootNode, errors);
    return { valid: errors.length === 0, errors };
  } catch {
    // Parser crash — don't block on this
    return { valid: true, errors: [] };
  }
}

/**
 * Validate an edit by checking if the "after" content introduces syntax errors.
 * Compares error count: if "after" has more errors than "before", reports the new ones.
 */
export function validateEdit(before: string, after: string, filePath: string): ValidationResult {
  const ext = path.extname(filePath).toLowerCase();
  const parser = getParser(ext);

  if (!parser) {
    return { valid: true, errors: [] };
  }

  try {
    const beforeErrors: SyntaxError[] = [];
    const afterErrors: SyntaxError[] = [];

    const beforeTree = parser.parse(before);
    collectErrors(beforeTree.rootNode, beforeErrors);

    const afterTree = parser.parse(after);
    collectErrors(afterTree.rootNode, afterErrors);

    // Only report if the edit introduced NEW errors
    if (afterErrors.length > beforeErrors.length) {
      const newErrors = afterErrors.slice(beforeErrors.length);
      return { valid: false, errors: newErrors };
    }

    return { valid: true, errors: [] };
  } catch {
    return { valid: true, errors: [] };
  }
}
