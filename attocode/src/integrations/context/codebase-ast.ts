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

export interface ASTParameter {
  name: string;
  typeAnnotation?: string;
  hasDefault: boolean;
  isRest: boolean;
}

export interface ASTDecorator {
  name: string;
  arguments?: string;
}

export interface ASTSymbol {
  name: string;
  kind: 'function' | 'class' | 'interface' | 'type' | 'variable' | 'enum' | 'method' | 'property';
  exported: boolean;
  line: number;
  /** End line of the symbol's scope */
  endLine?: number;
  /** Function/method parameters */
  parameters?: ASTParameter[];
  /** Return type annotation */
  returnType?: string;
  /** Visibility modifier */
  visibility?: 'public' | 'private' | 'protected';
  /** Whether the function/method is async */
  isAsync?: boolean;
  /** Whether the function/method is a generator */
  isGenerator?: boolean;
  /** Generic type parameters (e.g. ['T', 'K extends string']) */
  typeParameters?: string[];
  /** Decorators applied to this symbol */
  decorators?: ASTDecorator[];
  /** Name of the parent symbol (e.g. class name for methods) */
  parentSymbol?: string;
  /** Whether this is a static member */
  isStatic?: boolean;
  /** Whether this is abstract */
  isAbstract?: boolean;
}

export interface ASTDependency {
  source: string;
  names: string[];
  isRelative: boolean;
}

/** Result of diffing old vs new symbols after a file edit. */
export interface SymbolChange {
  symbol: ASTSymbol;
  changeKind: 'added' | 'removed' | 'modified';
  previousSymbol?: ASTSymbol;
}

/** Result of incremental file update processing. */
export interface FileChangeResult {
  filePath: string;
  symbolChanges: SymbolChange[];
  dependencyChanges: { added: ASTDependency[]; removed: ASTDependency[] };
  wasIncremental: boolean;
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
  endPosition?: { row: number; column: number };
  startIndex?: number;
  endIndex?: number;
  parent?: SyntaxNode | null;
  children?: SyntaxNode[];
  hasChanges?: boolean;
  child(index: number): SyntaxNode | null;
  childForFieldName(name: string): SyntaxNode | null;
  namedChildren: SyntaxNode[];
  descendantsOfType?(type: string | string[]): SyntaxNode[];
};

export type Tree = {
  rootNode: SyntaxNode;
  /** tree-sitter's edit method for incremental parsing */
  edit?(input: TreeEdit): Tree;
  /** Get ranges that changed between this tree and another */
  getChangedRanges?(other: Tree): Array<{
    startPosition: { row: number; column: number };
    endPosition: { row: number; column: number };
    startIndex: number;
    endIndex: number;
  }>;
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
// INCREMENTAL REPARSE UTILITIES
// =============================================================================

/**
 * Compute a TreeEdit from old content and a string replacement.
 * Returns null if the old_string is not found in oldContent.
 */
export function computeTreeEdit(
  oldContent: string,
  oldString: string,
  newString: string,
): TreeEdit | null {
  const startIndex = oldContent.indexOf(oldString);
  if (startIndex === -1) return null;

  const oldEndIndex = startIndex + oldString.length;
  const newEndIndex = startIndex + newString.length;

  const linesBefore = oldContent.slice(0, startIndex).split('\n');
  const startRow = linesBefore.length - 1;
  const startCol = linesBefore[linesBefore.length - 1].length;

  const oldEndLines = oldContent.slice(0, oldEndIndex).split('\n');
  const oldEndRow = oldEndLines.length - 1;
  const oldEndCol = oldEndLines[oldEndLines.length - 1].length;

  const newContent = oldContent.slice(0, startIndex) + newString + oldContent.slice(oldEndIndex);
  const newEndLines = newContent.slice(0, newEndIndex).split('\n');
  const newEndRow = newEndLines.length - 1;
  const newEndCol = newEndLines[newEndLines.length - 1].length;

  return {
    startIndex,
    oldEndIndex,
    newEndIndex,
    startPosition: { row: startRow, column: startCol },
    oldEndPosition: { row: oldEndRow, column: oldEndCol },
    newEndPosition: { row: newEndRow, column: newEndCol },
  };
}

/**
 * Diff two symbol arrays to detect additions, removals, and modifications.
 */
export function diffSymbols(oldSymbols: ASTSymbol[], newSymbols: ASTSymbol[]): SymbolChange[] {
  const changes: SymbolChange[] = [];
  const oldByKey = new Map<string, ASTSymbol>();
  const newByKey = new Map<string, ASTSymbol>();

  const symbolKey = (s: ASTSymbol) => `${s.kind}:${s.parentSymbol || ''}:${s.name}`;

  for (const s of oldSymbols) oldByKey.set(symbolKey(s), s);
  for (const s of newSymbols) newByKey.set(symbolKey(s), s);

  // Removed symbols
  for (const [key, sym] of oldByKey) {
    if (!newByKey.has(key)) {
      changes.push({ symbol: sym, changeKind: 'removed' });
    }
  }

  // Added or modified symbols
  for (const [key, sym] of newByKey) {
    const old = oldByKey.get(key);
    if (!old) {
      changes.push({ symbol: sym, changeKind: 'added' });
    } else if (
      old.line !== sym.line ||
      old.endLine !== sym.endLine ||
      old.exported !== sym.exported ||
      old.returnType !== sym.returnType ||
      old.isAsync !== sym.isAsync ||
      old.visibility !== sym.visibility ||
      JSON.stringify(old.parameters) !== JSON.stringify(sym.parameters)
    ) {
      changes.push({ symbol: sym, changeKind: 'modified', previousSymbol: old });
    }
  }

  return changes;
}

/**
 * Diff two dependency arrays to detect additions and removals.
 */
export function diffDependencies(
  oldDeps: ASTDependency[],
  newDeps: ASTDependency[],
): { added: ASTDependency[]; removed: ASTDependency[] } {
  const depKey = (d: ASTDependency) => `${d.source}:${d.names.sort().join(',')}`;
  const oldKeys = new Set(oldDeps.map(depKey));
  const newKeys = new Set(newDeps.map(depKey));

  return {
    added: newDeps.filter((d) => !oldKeys.has(depKey(d))),
    removed: oldDeps.filter((d) => !newKeys.has(depKey(d))),
  };
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

/** Extract parameters from a function/method parameter list node. */
function extractParameters(paramsNode: SyntaxNode | null): ASTParameter[] {
  if (!paramsNode) return [];
  const params: ASTParameter[] = [];
  for (const child of paramsNode.namedChildren) {
    if (
      child.type === 'required_parameter' ||
      child.type === 'optional_parameter' ||
      child.type === 'rest_parameter'
    ) {
      const patternNode = child.childForFieldName('pattern') ?? child.childForFieldName('name');
      const typeNode = child.childForFieldName('type');
      const valueNode = child.childForFieldName('value');
      params.push({
        name: patternNode?.text ?? child.text.split(/[?:=]/)[0].replace('...', '').trim(),
        typeAnnotation: typeNode?.text?.replace(/^:\s*/, ''),
        hasDefault: valueNode !== null,
        isRest: child.type === 'rest_parameter',
      });
    } else if (child.type === 'identifier') {
      // Simple JS parameter without type annotation
      params.push({ name: child.text, hasDefault: false, isRest: false });
    }
  }
  return params;
}

/** Extract generic type parameters (e.g. <T, K extends string>). */
function extractTypeParameters(node: SyntaxNode): string[] | undefined {
  const tpNode = node.childForFieldName('type_parameters');
  if (!tpNode) return undefined;
  const params: string[] = [];
  for (const child of tpNode.namedChildren) {
    if (child.type === 'type_parameter') {
      params.push(child.text);
    }
  }
  return params.length > 0 ? params : undefined;
}

/** Detect async/generator flags from a function/method node. */
function extractFunctionFlags(node: SyntaxNode): { isAsync?: boolean; isGenerator?: boolean } {
  const text = node.text;
  const flags: { isAsync?: boolean; isGenerator?: boolean } = {};
  // Check for 'async' keyword before the function body
  for (let i = 0; i < node.childCount; i++) {
    const child = node.child(i);
    if (child?.type === 'async') flags.isAsync = true;
  }
  if (!flags.isAsync && text.startsWith('async ')) flags.isAsync = true;
  // Generator: function* or *methodName
  if (text.includes('function*') || text.includes('* ')) flags.isGenerator = true;
  return flags;
}

/** Extract return type annotation from a function/method node. */
function extractReturnType(node: SyntaxNode): string | undefined {
  const returnType = node.childForFieldName('return_type');
  if (returnType) return returnType.text.replace(/^:\s*/, '');
  return undefined;
}

/** Detect visibility modifier on a class member. */
function detectVisibility(node: SyntaxNode): 'public' | 'private' | 'protected' | undefined {
  // Check for accessibility_modifier child
  for (let i = 0; i < node.childCount; i++) {
    const child = node.child(i);
    if (child?.type === 'accessibility_modifier') {
      const mod = child.text.trim();
      if (mod === 'private') return 'private';
      if (mod === 'protected') return 'protected';
      if (mod === 'public') return 'public';
    }
  }
  return undefined;
}

/** Collect decorators applied to a node. */
function collectDecorators(node: SyntaxNode): ASTDecorator[] | undefined {
  const decos: ASTDecorator[] = [];
  // Decorators are siblings preceding the node, or children of type 'decorator'
  for (let i = 0; i < node.childCount; i++) {
    const child = node.child(i);
    if (child?.type === 'decorator') {
      const nameNode = child.namedChildren[0];
      if (nameNode) {
        const argsNode = child.namedChildren.find((c) => c.type === 'arguments');
        decos.push({
          name: nameNode.text,
          arguments: argsNode ? argsNode.text : undefined,
        });
      }
    }
  }
  return decos.length > 0 ? decos : undefined;
}

/** Check if a node has 'static' keyword. */
function isStaticMember(node: SyntaxNode): boolean {
  for (let i = 0; i < node.childCount; i++) {
    const child = node.child(i);
    if (child?.type === 'static' || child?.text === 'static') return true;
  }
  return false;
}

/** Check if a node has 'abstract' keyword. */
function isAbstractMember(node: SyntaxNode): boolean {
  for (let i = 0; i < node.childCount; i++) {
    const child = node.child(i);
    if (child?.type === 'abstract' || child?.text === 'abstract') return true;
  }
  return false;
}

/** Get end line from a node (1-indexed). */
function getEndLine(node: SyntaxNode): number | undefined {
  return node.endPosition ? node.endPosition.row + 1 : undefined;
}

/** Build a fully detailed ASTSymbol for a function/class/interface declaration. */
function buildDetailedSymbol(
  node: SyntaxNode,
  kind: ASTSymbol['kind'],
  exported: boolean,
  parentSymbol?: string,
): ASTSymbol | null {
  const name = getDeclarationName(node);
  if (!name) return null;

  const sym: ASTSymbol = {
    name,
    kind,
    exported,
    line: node.startPosition.row + 1,
    endLine: getEndLine(node),
  };

  if (parentSymbol) sym.parentSymbol = parentSymbol;

  if (kind === 'function' || kind === 'method') {
    const paramsNode = node.childForFieldName('parameters');
    const params = extractParameters(paramsNode);
    if (params.length > 0) sym.parameters = params;
    sym.returnType = extractReturnType(node);
    const flags = extractFunctionFlags(node);
    if (flags.isAsync) sym.isAsync = true;
    if (flags.isGenerator) sym.isGenerator = true;
    sym.typeParameters = extractTypeParameters(node);
  }

  if (kind === 'class' || kind === 'interface') {
    sym.typeParameters = extractTypeParameters(node);
    if (isAbstractMember(node)) sym.isAbstract = true;
  }

  sym.decorators = collectDecorators(node);
  if (parentSymbol) {
    sym.visibility = detectVisibility(node);
    if (isStaticMember(node)) sym.isStatic = true;
    if (isAbstractMember(node)) sym.isAbstract = true;
  }

  return sym;
}

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
        const sym = buildDetailedSymbol(node, kind, false);
        if (sym) {
          symbols.push(sym);
          if (kind === 'class') {
            extractClassMembersDetailed(node, sym.name, symbols);
          }
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
      const sym = buildDetailedSymbol(decl, kind, true);
      if (sym) {
        symbols.push(sym);
        if (kind === 'class') {
          extractClassMembersDetailed(decl, sym.name, symbols);
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
              endLine: getEndLine(child),
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
        const sym = buildDetailedSymbol(child, kind, true);
        if (sym) {
          symbols.push(sym);
          if (kind === 'class') {
            extractClassMembersDetailed(child, sym.name, symbols);
          }
        }
      }
    }
  }
}

function extractClassMembersDetailed(
  classNode: SyntaxNode,
  className: string,
  symbols: ASTSymbol[],
): void {
  const body = classNode.childForFieldName('body');
  if (!body) return;

  for (const member of body.namedChildren) {
    if (member.type === 'method_definition') {
      const sym = buildDetailedSymbol(member, 'method', true, className);
      if (sym) symbols.push(sym);
    } else if (member.type === 'public_field_definition') {
      // Fix: public_field_definition is a property, not a method
      const nameNode = member.childForFieldName('name');
      if (nameNode) {
        const typeNode = member.childForFieldName('type');
        symbols.push({
          name: nameNode.text,
          kind: 'property',
          exported: true,
          line: member.startPosition.row + 1,
          endLine: getEndLine(member),
          parentSymbol: className,
          visibility: detectVisibility(member),
          isStatic: isStaticMember(member),
          returnType: typeNode?.text?.replace(/^:\s*/, ''),
          decorators: collectDecorators(member),
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

/** Extract Python function parameters. */
function extractPythonParameters(node: SyntaxNode): ASTParameter[] {
  const paramsNode = node.childForFieldName('parameters');
  if (!paramsNode) return [];
  const params: ASTParameter[] = [];
  for (const child of paramsNode.namedChildren) {
    if (child.type === 'identifier') {
      if (child.text !== 'self' && child.text !== 'cls') {
        params.push({ name: child.text, hasDefault: false, isRest: false });
      }
    } else if (child.type === 'typed_parameter') {
      const nameNode = child.namedChildren[0];
      const typeNode = child.childForFieldName('type');
      if (nameNode && nameNode.text !== 'self' && nameNode.text !== 'cls') {
        params.push({
          name: nameNode.text,
          typeAnnotation: typeNode?.text,
          hasDefault: false,
          isRest: false,
        });
      }
    } else if (child.type === 'default_parameter' || child.type === 'typed_default_parameter') {
      const nameNode = child.childForFieldName('name') ?? child.namedChildren[0];
      const typeNode = child.childForFieldName('type');
      if (nameNode) {
        params.push({
          name: nameNode.text,
          typeAnnotation: typeNode?.text,
          hasDefault: true,
          isRest: false,
        });
      }
    } else if (child.type === 'list_splat_pattern' || child.type === 'dictionary_splat_pattern') {
      const nameNode = child.namedChildren[0];
      if (nameNode) {
        params.push({ name: nameNode.text, hasDefault: false, isRest: true });
      }
    }
  }
  return params;
}

/** Extract Python return type annotation. */
function extractPythonReturnType(node: SyntaxNode): string | undefined {
  const returnType = node.childForFieldName('return_type');
  if (returnType) return returnType.text.replace(/^->\s*/, '');
  return undefined;
}

/** Collect Python decorators. */
function collectPythonDecorators(node: SyntaxNode): ASTDecorator[] | undefined {
  // In Python tree-sitter, decorators are `decorated_definition > decorator`
  // They appear as siblings or children before the function/class
  const parent = node.parent;
  if (!parent || parent.type !== 'decorated_definition') return undefined;
  const decos: ASTDecorator[] = [];
  for (const child of parent.namedChildren) {
    if (child.type === 'decorator') {
      // decorator text is like "@staticmethod" or "@app.route('/path')"
      const text = child.text.replace(/^@/, '');
      const parenIdx = text.indexOf('(');
      if (parenIdx > 0) {
        decos.push({
          name: text.slice(0, parenIdx),
          arguments: text.slice(parenIdx),
        });
      } else {
        decos.push({ name: text });
      }
    }
  }
  return decos.length > 0 ? decos : undefined;
}

function extractPythonSymbols(root: SyntaxNode): ASTSymbol[] {
  const symbols: ASTSymbol[] = [];

  const processNode = (node: SyntaxNode, parentClass?: string): void => {
    if (node.type === 'function_definition') {
      const nameNode = node.childForFieldName('name');
      if (nameNode) {
        const params = extractPythonParameters(node);
        const isAsync = node.parent?.type === 'decorated_definition'
          ? node.parent.text.startsWith('async ')
          : false;
        symbols.push({
          name: nameNode.text,
          kind: parentClass ? 'method' : 'function',
          exported: !nameNode.text.startsWith('_'),
          line: node.startPosition.row + 1,
          endLine: getEndLine(node),
          parameters: params.length > 0 ? params : undefined,
          returnType: extractPythonReturnType(node),
          isAsync: isAsync || undefined,
          decorators: collectPythonDecorators(node),
          parentSymbol: parentClass,
          isStatic: collectPythonDecorators(node)?.some((d) => d.name === 'staticmethod') || undefined,
        });
      }
    } else if (node.type === 'class_definition') {
      const nameNode = node.childForFieldName('name');
      if (nameNode) {
        symbols.push({
          name: nameNode.text,
          kind: 'class',
          exported: !nameNode.text.startsWith('_'),
          line: node.startPosition.row + 1,
          endLine: getEndLine(node),
          decorators: collectPythonDecorators(node),
        });
        // Extract class methods
        const body = node.childForFieldName('body');
        if (body) {
          for (const child of body.namedChildren) {
            if (child.type === 'function_definition') {
              processNode(child, nameNode.text);
            } else if (child.type === 'decorated_definition') {
              for (const inner of child.namedChildren) {
                if (inner.type === 'function_definition') {
                  processNode(inner, nameNode.text);
                }
              }
            }
          }
        }
      }
    } else if (node.type === 'decorated_definition') {
      // Process the inner definition
      for (const child of node.namedChildren) {
        if (child.type === 'function_definition' || child.type === 'class_definition') {
          processNode(child, parentClass);
        }
      }
    }
  };

  for (let i = 0; i < root.childCount; i++) {
    const node = root.child(i);
    if (node) processNode(node);
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
