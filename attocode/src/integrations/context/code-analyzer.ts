/**
 * Code Analyzer — AST + dependency analysis helpers
 *
 * Extracted from CodebaseContextManager (Phase 3d restructuring).
 * Contains file processing, symbol extraction, dependency analysis,
 * and importance scoring logic.
 */

import * as fs from 'fs/promises';
import * as path from 'path';
import { isASTSupported, extractSymbolsAST, extractDependenciesAST, type ASTSymbol } from './codebase-ast.js';
import type { CodeChunk, CodeChunkType, CodebaseContextConfig } from './codebase-context.js';

// =============================================================================
// DEPS INTERFACE
// =============================================================================

/**
 * Subset of CodebaseContextManager internals needed by analyzer functions.
 */
export interface CodeAnalyzerDeps {
  readonly config: Required<CodebaseContextConfig>;
}

// =============================================================================
// CONSTANTS
// =============================================================================

const ALWAYS_EXCLUDED_DIRS = new Set([
  'node_modules',
  '.git',
  'dist',
  'build',
  'coverage',
  '.next',
  'target',
  'vendor',
]);

// =============================================================================
// FILE DISCOVERY
// =============================================================================

/**
 * Discover files matching include patterns.
 */
export async function discoverFiles(deps: CodeAnalyzerDeps, root: string): Promise<string[]> {
  const files: string[] = [];

  const walk = async (dir: string): Promise<void> => {
    const entries = await fs.readdir(dir, { withFileTypes: true });

    for (const entry of entries) {
      const fullPath = path.join(dir, entry.name);
      const relativePath = normalizePath(path.relative(root, fullPath));

      // Check exclusions first
      if (entry.isDirectory() && ALWAYS_EXCLUDED_DIRS.has(entry.name)) {
        continue;
      }
      if (matchesPatterns(deps, relativePath, deps.config.excludePatterns)) {
        continue;
      }

      if (entry.isDirectory()) {
        await walk(fullPath);
      } else if (entry.isFile()) {
        if (matchesPatterns(deps, relativePath, deps.config.includePatterns)) {
          files.push(relativePath);
        }
      }
    }
  };

  await walk(root);
  return files;
}

// =============================================================================
// FILE PROCESSING
// =============================================================================

/**
 * Process a single file into a code chunk.
 */
export async function processFile(
  deps: CodeAnalyzerDeps,
  root: string,
  relativePath: string,
): Promise<CodeChunk | null> {
  const fullPath = path.join(root, relativePath);

  try {
    const stat = await fs.stat(fullPath);

    // Skip large files
    if (stat.size > deps.config.maxFileSize) {
      return null;
    }

    const content = await fs.readFile(fullPath, 'utf-8');
    const tokenCount = Math.ceil(content.length * deps.config.tokensPerChar);
    const type = determineChunkType(deps, relativePath, content);
    const symbolDetailsList = extractSymbolDetails(content, relativePath);
    const symbols = symbolDetailsList.length > 0
      ? symbolDetailsList.map((s) => s.name)
      : extractSymbols(content, relativePath);
    const dependencies = extractDependencyNames(content, relativePath);

    // Calculate base importance
    const importance = calculateBaseImportance(type, relativePath);

    return {
      id: relativePath,
      filePath: relativePath,
      content,
      tokenCount,
      importance,
      type,
      symbols,
      symbolDetails: symbolDetailsList,
      dependencies,
      lastModified: stat.mtime,
    };
  } catch {
    return null;
  }
}

// =============================================================================
// CHUNK TYPE CLASSIFICATION
// =============================================================================

/**
 * Determine the type of a code chunk.
 */
export function determineChunkType(
  deps: CodeAnalyzerDeps,
  filePath: string,
  content: string,
): CodeChunkType {
  const lower = filePath.toLowerCase();

  // Entry points
  if (matchesPatterns(deps, filePath, deps.config.entryPointPatterns)) {
    return 'entry_point';
  }

  // Tests
  if (
    lower.includes('.test.') ||
    lower.includes('.spec.') ||
    lower.includes('__tests__') ||
    lower.includes('/test/')
  ) {
    return 'test';
  }

  // Types/interfaces
  if (
    lower.includes('/types') ||
    lower.endsWith('.d.ts') ||
    (content.includes('interface ') && !content.includes('function '))
  ) {
    return 'types';
  }

  // Config
  if (
    lower.includes('config') ||
    lower.includes('settings') ||
    lower.endsWith('.json')
  ) {
    return 'config';
  }

  // Documentation
  if (lower.endsWith('.md') || lower.endsWith('.txt')) {
    return 'documentation';
  }

  // Utilities
  if (
    lower.includes('/utils/') ||
    lower.includes('/helpers/') ||
    lower.includes('/lib/')
  ) {
    return 'utility';
  }

  // Core modules (default for src/, services/, etc.)
  if (matchesPatterns(deps, filePath, deps.config.coreModulePatterns)) {
    return 'core_module';
  }

  return 'other';
}

// =============================================================================
// IMPORTANCE SCORING
// =============================================================================

/**
 * Calculate base importance for a chunk type.
 */
export function calculateBaseImportance(type: CodeChunkType, filePath: string): number {
  const typeScores: Record<CodeChunkType, number> = {
    entry_point: 0.95,
    core_module: 0.8,
    types: 0.7,
    config: 0.6,
    utility: 0.5,
    documentation: 0.3,
    test: 0.2,
    other: 0.4,
  };

  let score = typeScores[type];

  // Boost for shallow directory depth (closer to root = more important)
  const depth = filePath.split('/').length;
  score += Math.max(0, (5 - depth) * 0.02);

  // Boost for index files
  if (path.basename(filePath).startsWith('index.')) {
    score += 0.1;
  }

  return Math.min(1, score);
}

/**
 * Adjust importance based on how many files depend on each chunk.
 */
export function adjustImportanceByConnectivity(
  chunks: Map<string, CodeChunk>,
  reverseDeps: Map<string, Set<string>>,
): void {
  // Find max dependents for normalization
  let maxDependents = 1;
  for (const deps of reverseDeps.values()) {
    maxDependents = Math.max(maxDependents, deps.size);
  }

  // Adjust importance
  for (const [filePath, chunk] of chunks) {
    const dependents = reverseDeps.get(filePath)?.size ?? 0;
    const connectivityBoost = (dependents / maxDependents) * 0.2;
    chunk.importance = Math.min(1, chunk.importance + connectivityBoost);
  }
}

// =============================================================================
// SYMBOL EXTRACTION
// =============================================================================

/**
 * Extract exported symbols from code.
 * Uses AST-based extraction when available, with regex fallback.
 */
export function extractSymbols(content: string, filePath: string): string[] {
  // Try AST-based extraction first
  if (isASTSupported(filePath)) {
    const astSymbols = extractSymbolsAST(content, filePath);
    if (astSymbols.length > 0) {
      return astSymbols.map(s => s.name);
    }
  }

  // Fallback to regex extraction
  const symbols: string[] = [];
  const ext = path.extname(filePath);

  if (['.ts', '.tsx', '.js', '.jsx'].includes(ext)) {
    // Match exports
    const exportPatterns = [
      /export\s+(?:default\s+)?(?:class|function|const|let|var|interface|type|enum)\s+(\w+)/g,
      /export\s+\{\s*([^}]+)\s*\}/g,
    ];

    for (const pattern of exportPatterns) {
      let match;
      while ((match = pattern.exec(content)) !== null) {
        const captured = match[1];
        if (captured.includes(',')) {
          // Multiple exports
          symbols.push(...captured.split(',').map((s) => s.trim().split(' ')[0]));
        } else {
          symbols.push(captured);
        }
      }
    }
  } else if (ext === '.py') {
    // Python: class and def at module level
    const pyPatterns = [
      /^class\s+(\w+)/gm,
      /^def\s+(\w+)/gm,
    ];

    for (const pattern of pyPatterns) {
      let match;
      while ((match = pattern.exec(content)) !== null) {
        symbols.push(match[1]);
      }
    }
  }

  return symbols;
}

/**
 * Extract structured symbols from code.
 */
export function extractSymbolDetails(
  content: string,
  filePath: string,
): Array<{ name: string; kind: string; exported: boolean; line: number }> {
  if (isASTSupported(filePath)) {
    const astSymbols = extractSymbolsAST(content, filePath);
    if (astSymbols.length > 0) {
      return astSymbols.map((s: ASTSymbol) => ({
        name: s.name,
        kind: s.kind,
        exported: s.exported,
        line: s.line,
      }));
    }
  }

  const details: Array<{ name: string; kind: string; exported: boolean; line: number }> = [];
  const ext = path.extname(filePath);

  if (['.ts', '.tsx', '.js', '.jsx'].includes(ext)) {
    const addMatches = (kind: string, exported: boolean, pattern: RegExp) => {
      let match: RegExpExecArray | null;
      while ((match = pattern.exec(content)) !== null) {
        details.push({ name: match[1], kind, exported, line: 0 });
      }
    };
    addMatches('function', true, /export\s+(?:default\s+)?function\s+(\w+)/g);
    addMatches('class', true, /export\s+(?:default\s+)?class\s+(\w+)/g);
    addMatches('interface', true, /export\s+interface\s+(\w+)/g);
    addMatches('type', true, /export\s+type\s+(\w+)/g);
    addMatches('enum', true, /export\s+enum\s+(\w+)/g);
    addMatches('variable', true, /export\s+(?:const|let|var)\s+(\w+)/g);
    addMatches('function', false, /(?:^|\n)\s*function\s+(\w+)/g);
    addMatches('class', false, /(?:^|\n)\s*class\s+(\w+)/g);
  } else if (ext === '.py') {
    let match: RegExpExecArray | null;
    const classPattern = /^class\s+(\w+)/gm;
    while ((match = classPattern.exec(content)) !== null) {
      details.push({ name: match[1], kind: 'class', exported: true, line: 0 });
    }
    const fnPattern = /^def\s+(\w+)/gm;
    while ((match = fnPattern.exec(content)) !== null) {
      details.push({ name: match[1], kind: 'function', exported: true, line: 0 });
    }
  }

  const seen = new Set<string>();
  return details.filter((d) => {
    const key = `${d.kind}:${d.name}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

// =============================================================================
// DEPENDENCY EXTRACTION
// =============================================================================

/**
 * Extract dependency file paths from imports.
 * Uses AST-based extraction when available, with regex fallback.
 */
export function extractDependencies(content: string, currentFile: string): Set<string> {
  // Try AST-based extraction first
  if (isASTSupported(currentFile)) {
    const astDeps = extractDependenciesAST(content, currentFile);
    const deps = new Set<string>();
    const dir = path.dirname(currentFile);
    for (const dep of astDeps) {
      if (dep.isRelative) {
        const resolved = path.normalize(path.join(dir, dep.source));
        for (const tryExt of ['', '.ts', '.tsx', '.js', '.jsx', '/index.ts', '/index.js']) {
          deps.add(resolved + tryExt);
        }
      }
    }
    if (deps.size > 0) return deps;
  }

  // Fallback to regex extraction
  const deps = new Set<string>();
  const ext = path.extname(currentFile);
  const dir = path.dirname(currentFile);

  if (['.ts', '.tsx', '.js', '.jsx'].includes(ext)) {
    const importPattern = /import\s+.*?\s+from\s+['"]([^'"]+)['"]/g;
    let match;

    while ((match = importPattern.exec(content)) !== null) {
      const importPath = match[1];

      if (importPath.startsWith('.')) {
        const resolved = path.normalize(path.join(dir, importPath));

        for (const tryExt of ['', '.ts', '.tsx', '.js', '.jsx', '/index.ts', '/index.js']) {
          const tryPath = resolved + tryExt;
          deps.add(tryPath);
        }
      }
    }
  }

  return deps;
}

/**
 * Extract dependency names (for symbol matching).
 * Uses AST-based extraction when available, with regex fallback.
 */
export function extractDependencyNames(content: string, filePath?: string): string[] {
  // Try AST-based extraction first
  if (filePath && isASTSupported(filePath)) {
    const astDeps = extractDependenciesAST(content, filePath);
    if (astDeps.length > 0) {
      const names: string[] = [];
      for (const dep of astDeps) {
        names.push(...dep.names.filter(n => !n.startsWith('* as ')));
      }
      if (names.length > 0) return names;
    }
  }

  // Fallback to regex extraction
  const depNames: string[] = [];

  const patterns = [
    /import\s+\{\s*([^}]+)\s*\}\s+from/g,
    /import\s+(\w+)\s+from/g,
  ];

  for (const pattern of patterns) {
    let match;
    while ((match = pattern.exec(content)) !== null) {
      const captured = match[1];
      if (captured.includes(',')) {
        depNames.push(...captured.split(',').map((s) => s.trim().split(' ')[0]));
      } else {
        depNames.push(captured);
      }
    }
  }

  return depNames;
}

// =============================================================================
// PATTERN MATCHING
// =============================================================================

/**
 * Check if a path matches any of the given patterns.
 */
export function matchesPatterns(_deps: CodeAnalyzerDeps, filePath: string, patterns: string[]): boolean {
  const normalizedFilePath = normalizePath(filePath);
  for (const pattern of patterns) {
    if (matchesGlob(normalizedFilePath, pattern)) {
      return true;
    }
  }
  return false;
}

/**
 * Simple glob matching (supports * and **).
 */
export function matchesGlob(filePath: string, pattern: string): boolean {
  const normalizedFilePath = normalizePath(filePath);
  const normalizedPattern = normalizePath(pattern).replace(/^\.\/+/, '');
  const pathSegments = normalizedFilePath.split('/').filter(Boolean);
  const patternSegments = normalizedPattern.split('/').filter(Boolean);

  const matchSegment = (segment: string, segmentPattern: string): boolean => {
    if (segmentPattern === '*') return true;
    const escaped = segmentPattern
      .replace(/[.+^${}()|[\]\\]/g, '\\$&')
      .replace(/\*/g, '.*')
      .replace(/\?/g, '.');
    return new RegExp(`^${escaped}$`).test(segment);
  };

  const matchFrom = (pathIndex: number, patternIndex: number): boolean => {
    if (patternIndex >= patternSegments.length) {
      return pathIndex >= pathSegments.length;
    }

    const part = patternSegments[patternIndex];
    if (part === '**') {
      for (let i = pathIndex; i <= pathSegments.length; i++) {
        if (matchFrom(i, patternIndex + 1)) {
          return true;
        }
      }
      return false;
    }

    if (pathIndex >= pathSegments.length) {
      return false;
    }
    if (!matchSegment(pathSegments[pathIndex], part)) {
      return false;
    }
    return matchFrom(pathIndex + 1, patternIndex + 1);
  };

  return matchFrom(0, 0);
}

/**
 * Normalize a file path (forward slashes, no leading ./).
 */
export function normalizePath(value: string): string {
  return value
    .replaceAll('\\', '/')
    .replace(/^\.\/+/, '')
    .replace(/\/{2,}/g, '/');
}
