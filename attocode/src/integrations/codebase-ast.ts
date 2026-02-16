/**
 * Codebase AST Module (Phase 3.3)
 *
 * Replaces regex-based symbol extraction with tree-sitter AST parsing.
 * Provides accurate symbol and dependency extraction for TypeScript/TSX
 * and Python. Falls back gracefully when tree-sitter is unavailable.
 */

import * as path from 'path';

// =============================================================================
// TYPES
// =============================================================================

export interface ASTSymbol {
  name: string;
  kind: 'function' | 'class' | 'interface' | 'type' | 'variable' | 'enum' | 'method';
  exported: boolean;
  line: number;
}

export interface ASTDependency {
  source: string;
  names: string[];
  isRelative: boolean;
}

// =============================================================================
// LAZY PARSER INITIALIZATION
// =============================================================================

export type SyntaxNode = {
  type: string;
  text: string;
  isNamed: boolean;
  childCount: number;
  startPosition: { row: number; column: number };
  child(index: number): SyntaxNode | null;
  childForFieldName(name: string): SyntaxNode | null;
  namedChildren: SyntaxNode[];
};

export type Tree = { rootNode: SyntaxNode };

export type ParserLike = {
  setLanguage(lang: unknown): void;
  parse(input: string): Tree;
};

let tsParser: ParserLike | null = null;
let tsxParser: ParserLike | null = null;
let pyParser: ParserLike | null = null;
let parserInitAttempted = false;

export function getParser(ext: string): ParserLike | null {
  if (!parserInitAttempted) {
    parserInitAttempted = true;
    try {
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const Parser = require('tree-sitter');
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const tsLangs = require('tree-sitter-typescript');

      tsParser = new Parser();
      (tsParser as ParserLike).setLanguage(tsLangs.typescript);

      tsxParser = new Parser();
      (tsxParser as ParserLike).setLanguage(tsLangs.tsx);

      try {
        // eslint-disable-next-line @typescript-eslint/no-require-imports
        const pyLang = require('tree-sitter-python');
        pyParser = new Parser();
        (pyParser as ParserLike).setLanguage(pyLang);
      } catch {
        // Python grammar not available — not fatal
      }
    } catch {
      // tree-sitter not available at all
      tsParser = null;
      tsxParser = null;
      pyParser = null;
    }
  }

  switch (ext) {
    case '.ts': return tsParser;
    case '.tsx': return tsxParser;
    case '.js': return tsParser;  // TS parser handles JS fine
    case '.jsx': return tsxParser;
    case '.py': return pyParser;
    default: return null;
  }
}

// =============================================================================
// PUBLIC API
// =============================================================================

/**
 * Check if AST parsing is available for a file extension.
 */
export function isASTSupported(filePath: string): boolean {
  const ext = path.extname(filePath).toLowerCase();
  return getParser(ext) !== null;
}

/**
 * Extract symbols from source code using tree-sitter AST.
 */
export function extractSymbolsAST(content: string, filePath: string): ASTSymbol[] {
  const ext = path.extname(filePath).toLowerCase();
  const parser = getParser(ext);
  if (!parser) return [];

  try {
    const tree = parser.parse(content);
    if (ext === '.py') {
      return extractPythonSymbols(tree.rootNode);
    }
    return extractTSSymbols(tree.rootNode);
  } catch {
    return [];
  }
}

/**
 * Extract dependencies from source code using tree-sitter AST.
 */
export function extractDependenciesAST(content: string, filePath: string): ASTDependency[] {
  const ext = path.extname(filePath).toLowerCase();
  const parser = getParser(ext);
  if (!parser) return [];

  try {
    const tree = parser.parse(content);
    if (ext === '.py') {
      return extractPythonDependencies(tree.rootNode);
    }
    return extractTSDependencies(tree.rootNode);
  } catch {
    return [];
  }
}

// =============================================================================
// TYPESCRIPT / JAVASCRIPT EXTRACTION
// =============================================================================

function extractTSSymbols(root: SyntaxNode): ASTSymbol[] {
  const symbols: ASTSymbol[] = [];

  for (let i = 0; i < root.childCount; i++) {
    const node = root.child(i);
    if (!node) continue;

    if (node.type === 'export_statement') {
      extractFromExportStatement(node, symbols);
    } else {
      // Non-exported top-level declarations
      const kind = declarationKind(node.type);
      if (kind) {
        const name = getDeclarationName(node);
        if (name) {
          symbols.push({
            name,
            kind,
            exported: false,
            line: node.startPosition.row + 1,
          });
        }
      }
    }
  }

  return symbols;
}

function extractFromExportStatement(exportNode: SyntaxNode, symbols: ASTSymbol[]): void {
  const decl = exportNode.childForFieldName('declaration');

  if (decl) {
    const kind = declarationKind(decl.type);
    if (kind) {
      const name = getDeclarationName(decl);
      if (name) {
        symbols.push({
          name,
          kind,
          exported: true,
          line: decl.startPosition.row + 1,
        });

        // Extract class methods
        if (kind === 'class') {
          extractClassMembers(decl, symbols);
        }
      }
    } else if (decl.type === 'lexical_declaration') {
      // export const x = 1; export let y = 2;
      for (const child of decl.namedChildren) {
        if (child.type === 'variable_declarator') {
          const nameNode = child.childForFieldName('name');
          if (nameNode) {
            symbols.push({
              name: nameNode.text,
              kind: 'variable',
              exported: true,
              line: child.startPosition.row + 1,
            });
          }
        }
      }
    }
    return;
  }

  // export { A, B } or export { A, B } from './other'
  for (let i = 0; i < exportNode.childCount; i++) {
    const child = exportNode.child(i);
    if (!child) continue;

    if (child.type === 'export_clause') {
      for (const specifier of child.namedChildren) {
        if (specifier.type === 'export_specifier') {
          const nameNode = specifier.childForFieldName('name');
          if (nameNode) {
            symbols.push({
              name: nameNode.text,
              kind: 'variable', // We don't know the kind from re-exports
              exported: true,
              line: specifier.startPosition.row + 1,
            });
          }
        }
      }
    }
  }

  // export default class/function (without declaration field — fallback)
  let hasDefault = false;
  for (let i = 0; i < exportNode.childCount; i++) {
    const child = exportNode.child(i);
    if (child?.type === 'default') hasDefault = true;
  }
  if (hasDefault && !decl) {
    // Check for inline class/function after 'default'
    for (let i = 0; i < exportNode.childCount; i++) {
      const child = exportNode.child(i);
      if (!child) continue;
      const kind = declarationKind(child.type);
      if (kind) {
        const name = getDeclarationName(child);
        symbols.push({
          name: name || 'default',
          kind,
          exported: true,
          line: child.startPosition.row + 1,
        });
        if (kind === 'class') {
          extractClassMembers(child, symbols);
        }
      }
    }
  }
}

function extractClassMembers(classNode: SyntaxNode, symbols: ASTSymbol[]): void {
  const body = classNode.childForFieldName('body');
  if (!body) return;

  for (const member of body.namedChildren) {
    if (member.type === 'method_definition' || member.type === 'public_field_definition') {
      const nameNode = member.childForFieldName('name');
      if (nameNode) {
        symbols.push({
          name: nameNode.text,
          kind: 'method',
          exported: true,
          line: member.startPosition.row + 1,
        });
      }
    }
  }
}

function extractTSDependencies(root: SyntaxNode): ASTDependency[] {
  const deps: ASTDependency[] = [];

  for (let i = 0; i < root.childCount; i++) {
    const node = root.child(i);
    if (!node) continue;

    if (node.type === 'import_statement') {
      const dep = extractImportDependency(node);
      if (dep) deps.push(dep);
    }

    // Also handle export ... from '...'
    if (node.type === 'export_statement') {
      const source = findSourceString(node);
      if (source) {
        const names = extractExportNames(node);
        deps.push({
          source,
          names,
          isRelative: source.startsWith('.'),
        });
      }
    }
  }

  return deps;
}

function extractImportDependency(importNode: SyntaxNode): ASTDependency | null {
  const sourceNode = importNode.childForFieldName('source');
  if (!sourceNode) {
    // Side-effect import: import './init' — source is a direct string child
    for (let i = 0; i < importNode.childCount; i++) {
      const child = importNode.child(i);
      if (child?.type === 'string') {
        const source = stripQuotes(child.text);
        return { source, names: [], isRelative: source.startsWith('.') };
      }
    }
    return null;
  }

  const source = stripQuotes(sourceNode.text);
  const names: string[] = [];

  // Find the import_clause
  for (let i = 0; i < importNode.childCount; i++) {
    const child = importNode.child(i);
    if (child?.type === 'import_clause') {
      extractImportClauseNames(child, names);
    }
  }

  return { source, names, isRelative: source.startsWith('.') };
}

function extractImportClauseNames(clause: SyntaxNode, names: string[]): void {
  for (let i = 0; i < clause.childCount; i++) {
    const child = clause.child(i);
    if (!child) continue;

    if (child.type === 'identifier') {
      // Default import
      names.push(child.text);
    } else if (child.type === 'named_imports') {
      for (const specifier of child.namedChildren) {
        if (specifier.type === 'import_specifier') {
          const nameNode = specifier.childForFieldName('name');
          if (nameNode) names.push(nameNode.text);
        }
      }
    } else if (child.type === 'namespace_import') {
      // import * as NS
      const nameNode = child.childForFieldName('name') ?? child.namedChildren.find(c => c.type === 'identifier');
      if (nameNode) names.push(`* as ${nameNode.text}`);
    }
  }
}

function extractExportNames(exportNode: SyntaxNode): string[] {
  const names: string[] = [];
  for (let i = 0; i < exportNode.childCount; i++) {
    const child = exportNode.child(i);
    if (child?.type === 'export_clause') {
      for (const specifier of child.namedChildren) {
        if (specifier.type === 'export_specifier') {
          const nameNode = specifier.childForFieldName('name');
          if (nameNode) names.push(nameNode.text);
        }
      }
    }
  }
  return names;
}

function findSourceString(node: SyntaxNode): string | null {
  for (let i = 0; i < node.childCount; i++) {
    const child = node.child(i);
    if (child?.type === 'string' || child?.type === 'string_fragment') {
      return stripQuotes(child.text);
    }
  }
  // Check if the 'source' field exists
  const source = node.childForFieldName('source');
  if (source) return stripQuotes(source.text);
  return null;
}

// =============================================================================
// PYTHON EXTRACTION
// =============================================================================

function extractPythonSymbols(root: SyntaxNode): ASTSymbol[] {
  const symbols: ASTSymbol[] = [];

  for (let i = 0; i < root.childCount; i++) {
    const node = root.child(i);
    if (!node) continue;

    if (node.type === 'function_definition') {
      const name = node.childForFieldName('name');
      if (name) {
        symbols.push({
          name: name.text,
          kind: 'function',
          exported: !name.text.startsWith('_'),
          line: node.startPosition.row + 1,
        });
      }
    } else if (node.type === 'class_definition') {
      const name = node.childForFieldName('name');
      if (name) {
        symbols.push({
          name: name.text,
          kind: 'class',
          exported: !name.text.startsWith('_'),
          line: node.startPosition.row + 1,
        });
      }
    }
  }

  return symbols;
}

function extractPythonDependencies(root: SyntaxNode): ASTDependency[] {
  const deps: ASTDependency[] = [];

  for (let i = 0; i < root.childCount; i++) {
    const node = root.child(i);
    if (!node) continue;

    if (node.type === 'import_statement') {
      // import module
      for (const child of node.namedChildren) {
        if (child.type === 'dotted_name') {
          deps.push({
            source: child.text,
            names: [child.text],
            isRelative: false,
          });
        } else if (child.type === 'aliased_import') {
          const nameNode = child.childForFieldName('name');
          if (nameNode) {
            deps.push({
              source: nameNode.text,
              names: [nameNode.text],
              isRelative: false,
            });
          }
        }
      }
    } else if (node.type === 'import_from_statement') {
      // from module import name
      let source = '';
      let isRelative = false;
      const names: string[] = [];

      for (let j = 0; j < node.childCount; j++) {
        const child = node.child(j);
        if (!child) continue;

        if (child.type === 'dotted_name' && source === '') {
          source = child.text;
        } else if (child.type === 'relative_import') {
          source = child.text;
          isRelative = true;
        } else if (child.type === 'dotted_name' && source !== '') {
          names.push(child.text);
        } else if (child.type === 'aliased_import') {
          const nameNode = child.childForFieldName('name');
          if (nameNode) names.push(nameNode.text);
        }
      }

      if (source) {
        deps.push({ source, names, isRelative });
      }
    }
  }

  return deps;
}

// =============================================================================
// HELPERS
// =============================================================================

function declarationKind(nodeType: string): ASTSymbol['kind'] | null {
  switch (nodeType) {
    case 'function_declaration': return 'function';
    case 'class_declaration': return 'class';
    case 'interface_declaration': return 'interface';
    case 'type_alias_declaration': return 'type';
    case 'enum_declaration': return 'enum';
    default: return null;
  }
}

function getDeclarationName(node: SyntaxNode): string | null {
  const nameNode = node.childForFieldName('name');
  return nameNode?.text ?? null;
}

function stripQuotes(str: string): string {
  if ((str.startsWith("'") && str.endsWith("'")) ||
      (str.startsWith('"') && str.endsWith('"'))) {
    return str.slice(1, -1);
  }
  return str;
}
