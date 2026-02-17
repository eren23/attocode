/**
 * Codebase AST Module
 *
 * Provides accurate symbol and dependency extraction using tree-sitter AST parsing.
 * Supports TypeScript/TSX, JavaScript/JSX, Python, and polyglot languages via
 * pluggable language profiles.
 *
 * Key features:
 * - ASTCache: Parse once per file, extract symbols + dependencies from single tree
 * - Content-hash invalidation: Detects when file content changes
 * - Incremental reparse: Leverages tree-sitter's tree.edit() for fast updates
 * - Polyglot support: Unified LanguageProfile system for adding new languages
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

/** Cached parse result for a single file. */
export interface ParsedFile {
  /** Retained tree-sitter tree (needed for incremental parsing) */
  tree: Tree;
  /** Extracted symbols */
  symbols: ASTSymbol[];
  /** Extracted dependencies */
  dependencies: ASTDependency[];
  /** Content hash for invalidation (djb2) */
  contentHash: number;
  /** Timestamp of last parse */
  parsedAt: number;
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

export type Tree = {
  rootNode: SyntaxNode;
  /** tree-sitter's edit method for incremental parsing */
  edit?(input: TreeEdit): void;
};

export interface TreeEdit {
  startIndex: number;
  oldEndIndex: number;
  newEndIndex: number;
  startPosition: { row: number; column: number };
  oldEndPosition: { row: number; column: number };
  newEndPosition: { row: number; column: number };
}

export type ParserLike = {
  setLanguage(lang: unknown): void;
  parse(input: string, oldTree?: Tree): Tree;
};

let tsParser: ParserLike | null = null;
let tsxParser: ParserLike | null = null;
let pyParser: ParserLike | null = null;
let parserInitAttempted = false;
const parserInitFailed = new Set<string>();
const parsers = new Map<string, ParserLike>();

export function getParser(ext: string): ParserLike | null {
  // Check polyglot parser cache first
  if (parsers.has(ext)) return parsers.get(ext)!;
  if (parserInitFailed.has(ext)) return null;

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
    case '.ts':
      return tsParser;
    case '.tsx':
      return tsxParser;
    case '.js':
      return tsParser; // TS parser handles JS fine
    case '.jsx':
      return tsxParser;
    case '.py':
      return pyParser;
    default: {
      // Try polyglot language profiles (LANGUAGE_PROFILES defined below, accessed lazily at call time)
      const profile = getLanguageProfile(ext);
      if (!profile) return null;
      return initPolyglotParser(ext, profile);
    }
  }
}

// =============================================================================
// AST CACHE
// =============================================================================

/** Module-level cache: filePath (absolute) -> ParsedFile */
const astCache = new Map<string, ParsedFile>();

/** Module-level parse counters for diagnostics visibility. */
let totalParses = 0;
let cacheHits = 0;

/** Normalize cache key to absolute path to prevent absolute/relative mismatch. */
function cacheKey(filePath: string): string {
  return path.resolve(filePath);
}

/**
 * djb2 string hash — fast, non-cryptographic hash for content invalidation.
 */
export function djb2Hash(str: string): number {
  let hash = 5381;
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) + hash + str.charCodeAt(i)) | 0;
  }
  return hash >>> 0; // Ensure unsigned
}

/**
 * Parse a file once and extract symbols + dependencies from the same tree.
 * Results are cached by filePath + contentHash.
 */
export function parseFile(content: string, filePath: string): ParsedFile | null {
  const ext = path.extname(filePath).toLowerCase();
  const parser = getParser(ext);
  if (!parser) return null;

  const hash = djb2Hash(content);
  const key = cacheKey(filePath);

  // Check cache
  const cached = astCache.get(key);
  if (cached && cached.contentHash === hash) {
    cacheHits++;
    return cached;
  }

  try {
    totalParses++;
    const tree = parser.parse(content);
    const symbols = extractSymbolsFromRoot(tree.rootNode, ext);
    const dependencies = extractDependenciesFromRoot(tree.rootNode, ext);

    const result: ParsedFile = {
      tree,
      symbols,
      dependencies,
      contentHash: hash,
      parsedAt: Date.now(),
    };
    astCache.set(key, result);
    return result;
  } catch {
    return null;
  }
}

/**
 * Full reparse for write_file (no edit ranges available).
 * Parses from scratch and caches the result.
 */
export function fullReparse(filePath: string, newContent: string): ParsedFile | null {
  return parseFile(newContent, filePath);
}

/**
 * Incremental reparse using tree-sitter's tree.edit() + old tree reference.
 * Falls back to full reparse if no cached tree is available.
 */
export function incrementalReparse(
  filePath: string,
  newContent: string,
  edit: TreeEdit,
): ParsedFile | null {
  const key = cacheKey(filePath);
  const cached = astCache.get(key);
  const ext = path.extname(filePath).toLowerCase();
  const parser = getParser(ext);
  if (!parser) return null;

  try {
    let newTree: Tree;
    if (cached?.tree?.edit) {
      // Incremental: edit old tree, reparse with old tree reference
      cached.tree.edit(edit);
      newTree = parser.parse(newContent, cached.tree);
    } else {
      // No cached tree — full parse
      newTree = parser.parse(newContent);
    }

    const symbols = extractSymbolsFromRoot(newTree.rootNode, ext);
    const dependencies = extractDependenciesFromRoot(newTree.rootNode, ext);

    const hash = djb2Hash(newContent);
    const result: ParsedFile = {
      tree: newTree,
      symbols,
      dependencies,
      contentHash: hash,
      parsedAt: Date.now(),
    };
    astCache.set(key, result);
    return result;
  } catch {
    // Fall back to full reparse
    return parseFile(newContent, filePath);
  }
}

/** Remove a single file from the cache. */
export function invalidateAST(filePath: string): void {
  astCache.delete(cacheKey(filePath));
}

/** Clear all cached parse results. */
export function clearASTCache(): void {
  astCache.clear();
}

/** Get number of cached files. */
export function getASTCacheSize(): number {
  return astCache.size;
}

/** Get cached parse result without re-parsing. */
export function getCachedParse(filePath: string): ParsedFile | null {
  return astCache.get(cacheKey(filePath)) ?? null;
}

/** Get AST cache diagnostics stats. */
export function getASTCacheStats(): {
  fileCount: number;
  languages: Record<string, number>;
  totalParses: number;
  cacheHits: number;
} {
  const languages: Record<string, number> = {};
  for (const [key] of astCache) {
    const ext = key.slice(key.lastIndexOf('.')).toLowerCase();
    const lang =
      ext === '.ts' || ext === '.tsx'
        ? 'typescript'
        : ext === '.js' || ext === '.jsx'
          ? 'javascript'
          : ext === '.py'
            ? 'python'
            : ext;
    languages[lang] = (languages[lang] || 0) + 1;
  }
  return { fileCount: astCache.size, languages, totalParses, cacheHits };
}

/** Reset parse counters (for testing). */
export function resetASTCacheStats(): void {
  totalParses = 0;
  cacheHits = 0;
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
 * Uses ASTCache — parses once, reuses cached result.
 */
export function extractSymbolsAST(content: string, filePath: string): ASTSymbol[] {
  return parseFile(content, filePath)?.symbols ?? [];
}

/**
 * Extract dependencies from source code using tree-sitter AST.
 * Uses ASTCache — parses once, reuses cached result.
 */
export function extractDependenciesAST(content: string, filePath: string): ASTDependency[] {
  return parseFile(content, filePath)?.dependencies ?? [];
}

// =============================================================================
// INTERNAL: Root-level extraction dispatchers
// =============================================================================

/** Lookup a polyglot language profile by extension. */
function getLanguageProfile(ext: string): LanguageProfile | undefined {
  return LANGUAGE_PROFILES.find((p) => p.extensions.includes(ext));
}

function extractSymbolsFromRoot(root: SyntaxNode, ext: string): ASTSymbol[] {
  if (ext === '.py') return extractPythonSymbols(root);
  const profile = getLanguageProfile(ext);
  if (profile) return extractSymbolsGeneric(root, profile);
  return extractTSSymbols(root);
}

function extractDependenciesFromRoot(root: SyntaxNode, ext: string): ASTDependency[] {
  if (ext === '.py') return extractPythonDependencies(root);
  const profile = getLanguageProfile(ext);
  if (profile) return extractDependenciesGeneric(root, profile);
  return extractTSDependencies(root);
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
      const nameNode =
        child.childForFieldName('name') ?? child.namedChildren.find((c) => c.type === 'identifier');
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
    case 'function_declaration':
      return 'function';
    case 'class_declaration':
      return 'class';
    case 'interface_declaration':
      return 'interface';
    case 'type_alias_declaration':
      return 'type';
    case 'enum_declaration':
      return 'enum';
    default:
      return null;
  }
}

function getDeclarationName(node: SyntaxNode): string | null {
  const nameNode = node.childForFieldName('name');
  return nameNode?.text ?? null;
}

function stripQuotes(str: string): string {
  if ((str.startsWith("'") && str.endsWith("'")) || (str.startsWith('"') && str.endsWith('"'))) {
    return str.slice(1, -1);
  }
  return str;
}

// =============================================================================
// POLYGLOT LANGUAGE PROFILES (Phase 4)
// =============================================================================

export type ExportDetection = 'visibility' | 'keyword' | 'convention';

export interface LanguageProfile {
  extensions: string[];
  grammar: string;
  symbolNodes: Record<string, ASTSymbol['kind']>;
  importNodes: string[];
  exportDetection: ExportDetection;
  extractImport: (node: SyntaxNode) => ASTDependency[];
}

export const LANGUAGE_PROFILES: LanguageProfile[] = [
  {
    extensions: ['.go'],
    grammar: 'tree-sitter-go',
    symbolNodes: {
      function_declaration: 'function',
      method_declaration: 'method',
      type_declaration: 'class',
    },
    importNodes: ['import_declaration'],
    exportDetection: 'convention',
    extractImport: (node: SyntaxNode): ASTDependency[] => {
      // Go: import "pkg" or import ( "pkg1"; "pkg2" )
      const deps: ASTDependency[] = [];
      const walkImport = (n: SyntaxNode): void => {
        if (n.type === 'import_spec' || n.type === 'interpreted_string_literal') {
          const source = stripQuotes(n.text);
          if (source && !source.startsWith('(')) {
            deps.push({
              source,
              names: [path.basename(source)],
              isRelative: source.startsWith('.'),
            });
          }
        }
        for (const child of n.namedChildren) walkImport(child);
      };
      walkImport(node);
      return deps;
    },
  },
  {
    extensions: ['.rs'],
    grammar: 'tree-sitter-rust',
    symbolNodes: {
      function_item: 'function',
      impl_item: 'class',
      struct_item: 'class',
      enum_item: 'enum',
      trait_item: 'interface',
      type_item: 'type',
    },
    importNodes: ['use_declaration'],
    exportDetection: 'keyword',
    extractImport: (node: SyntaxNode): ASTDependency[] => {
      const text = node.text;
      const match = /use\s+(.+?)(?:\s+as\s+\w+)?;/.exec(text);
      if (match) {
        const source = match[1].replace(/::/g, '/');
        return [
          {
            source,
            names: [path.basename(source)],
            isRelative: source.startsWith('self') || source.startsWith('super'),
          },
        ];
      }
      return [];
    },
  },
  {
    extensions: ['.java'],
    grammar: 'tree-sitter-java',
    symbolNodes: {
      class_declaration: 'class',
      interface_declaration: 'interface',
      method_declaration: 'method',
      enum_declaration: 'enum',
    },
    importNodes: ['import_declaration'],
    exportDetection: 'visibility',
    extractImport: (node: SyntaxNode): ASTDependency[] => {
      const text = node.text;
      const match = /import\s+(?:static\s+)?(.+?);/.exec(text);
      if (match) {
        const source = match[1];
        const parts = source.split('.');
        return [{ source, names: [parts[parts.length - 1]], isRelative: false }];
      }
      return [];
    },
  },
  {
    extensions: ['.c', '.h'],
    grammar: 'tree-sitter-c',
    symbolNodes: {
      function_definition: 'function',
      struct_specifier: 'class',
      enum_specifier: 'enum',
      type_definition: 'type',
    },
    importNodes: ['preproc_include'],
    exportDetection: 'convention',
    extractImport: (node: SyntaxNode): ASTDependency[] => {
      const text = node.text;
      const match = /#include\s+[<"](.+?)[>"]/.exec(text);
      if (match) {
        const source = match[1];
        return [
          {
            source,
            names: [path.basename(source)],
            isRelative: source.includes('/') || text.includes('"'),
          },
        ];
      }
      return [];
    },
  },
  {
    extensions: ['.cpp', '.cc', '.cxx', '.hpp'],
    grammar: 'tree-sitter-cpp',
    symbolNodes: {
      function_definition: 'function',
      class_specifier: 'class',
      struct_specifier: 'class',
      enum_specifier: 'enum',
      namespace_definition: 'variable',
    },
    importNodes: ['preproc_include'],
    exportDetection: 'convention',
    extractImport: (node: SyntaxNode): ASTDependency[] => {
      const text = node.text;
      const match = /#include\s+[<"](.+?)[>"]/.exec(text);
      if (match) {
        const source = match[1];
        return [
          {
            source,
            names: [path.basename(source)],
            isRelative: source.includes('/') || text.includes('"'),
          },
        ];
      }
      return [];
    },
  },
  {
    extensions: ['.rb'],
    grammar: 'tree-sitter-ruby',
    symbolNodes: {
      method: 'function',
      singleton_method: 'function',
      class: 'class',
      module: 'class',
    },
    importNodes: ['call'],
    exportDetection: 'convention',
    extractImport: (node: SyntaxNode): ASTDependency[] => {
      const text = node.text;
      const match = /(?:require|require_relative)\s+['"](.+?)['"]/.exec(text);
      if (match) {
        const source = match[1];
        return [
          { source, names: [path.basename(source)], isRelative: text.includes('require_relative') },
        ];
      }
      return [];
    },
  },
  {
    extensions: ['.sh', '.bash'],
    grammar: 'tree-sitter-bash',
    symbolNodes: {
      function_definition: 'function',
    },
    importNodes: ['command'],
    exportDetection: 'convention',
    extractImport: (node: SyntaxNode): ASTDependency[] => {
      const text = node.text;
      const match = /(?:source|\.)\s+['"]?(.+?)['"]?(?:\s|$)/.exec(text);
      if (match) {
        const source = match[1];
        return [
          {
            source,
            names: [path.basename(source)],
            isRelative: source.startsWith('.') || source.startsWith('/'),
          },
        ];
      }
      return [];
    },
  },
];

// =============================================================================
// POLYGLOT: GENERIC EXTRACTORS
// =============================================================================

function initPolyglotParser(ext: string, profile: LanguageProfile): ParserLike | null {
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const Parser = require('tree-sitter');
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const lang = require(profile.grammar);
    const parser = new Parser() as ParserLike;
    parser.setLanguage(lang.default ?? lang);
    parsers.set(ext, parser);
    return parser;
  } catch {
    parserInitFailed.add(ext);
    return null;
  }
}

function extractSymbolsGeneric(root: SyntaxNode, profile: LanguageProfile): ASTSymbol[] {
  const symbols: ASTSymbol[] = [];
  walkTopLevel(root, (node) => {
    const kind = profile.symbolNodes[node.type];
    if (kind) {
      const name = getDeclarationName(node);
      if (name) {
        const exported = detectExport(node, name, profile.exportDetection);
        symbols.push({ name, kind, exported, line: node.startPosition.row + 1 });
      }
    }
  });
  return symbols;
}

function extractDependenciesGeneric(root: SyntaxNode, profile: LanguageProfile): ASTDependency[] {
  const deps: ASTDependency[] = [];
  walkTopLevel(root, (node) => {
    if (profile.importNodes.includes(node.type)) {
      deps.push(...profile.extractImport(node));
    }
  });
  return deps;
}

function walkTopLevel(root: SyntaxNode, callback: (node: SyntaxNode) => void): void {
  for (let i = 0; i < root.childCount; i++) {
    const node = root.child(i);
    if (node) callback(node);
  }
}

function detectExport(node: SyntaxNode, name: string, detection: ExportDetection): boolean {
  switch (detection) {
    case 'convention':
      // Go: uppercase first letter = exported; C/C++/Ruby/Bash: treat all as exported
      return (
        name.length > 0 && name[0] === name[0].toUpperCase() && name[0] !== name[0].toLowerCase()
      );
    case 'keyword': {
      // Rust: check for 'pub' keyword
      const nodeText = node.text;
      return nodeText.startsWith('pub ') || nodeText.startsWith('pub(');
    }
    case 'visibility': {
      // Java: check for 'public' modifier
      const nodeText = node.text;
      return nodeText.includes('public ');
    }
    default:
      return true;
  }
}
