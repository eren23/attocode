/**
 * Code Selector — Token-budget selection + ranking
 *
 * Extracted from CodebaseContextManager (Phase 3d restructuring).
 * Contains relevance scoring, strategy-based sorting, budget-constrained
 * selection, LSP-enhanced context, search, and incremental expansion.
 */

import * as path from 'path';
import type { LSPManager } from '../lsp/lsp.js';
import type {
  CodeChunk,
  RepoMap,
  SelectionOptions,
  SelectionStrategy,
  SelectionResult,
  EnhancedContextOptions,
  EnhancedContextResult,
  LSPEnhancements,
  SourcePosition,
  SearchOptions,
  RankedSearchOptions,
  ScoredChunk,
  CodebaseContextEvent,
} from './codebase-context.js';

// =============================================================================
// DEPS INTERFACE
// =============================================================================

/**
 * Subset of CodebaseContextManager internals needed by selector functions.
 */
export interface CodeSelectorDeps {
  readonly repoMap: RepoMap | null;
  readonly lspManager: LSPManager | null;
  hasActiveLSP(): boolean;
  analyze(): Promise<RepoMap>;
  emit(event: CodebaseContextEvent): void;
}

// =============================================================================
// SELECTION
// =============================================================================

/**
 * Select relevant code chunks for a task within a token budget.
 */
export async function selectRelevantCode(
  deps: CodeSelectorDeps,
  options: SelectionOptions,
): Promise<SelectionResult> {
  // Ensure we have an analyzed repo
  if (!deps.repoMap) {
    await deps.analyze();
  }

  const repoMap = deps.repoMap!;
  const {
    maxTokens,
    task,
    priorityFiles = [],
    minImportance = 0,
    includeTypes = true,
    includeTests = false,
    strategy = 'importance_first',
  } = options;

  // Get all candidate chunks
  let candidates = Array.from(repoMap.chunks.values()).filter((chunk) => {
    if (chunk.importance < minImportance) return false;
    if (!includeTypes && chunk.type === 'types') return false;
    if (!includeTests && chunk.type === 'test') return false;
    return true;
  });

  // Calculate relevance scores if task is provided
  if (task) {
    candidates = candidates.map((chunk) => ({
      ...chunk,
      relevance: calculateRelevance(chunk, task),
    }));
  }

  // Sort based on strategy
  candidates = sortByStrategy(candidates, strategy, task);

  // Select within budget
  const selected: CodeChunk[] = [];
  let totalTokens = 0;
  const excluded: string[] = [];

  // Prioritize specific files first
  for (const priorityFile of priorityFiles) {
    const chunk = repoMap.chunks.get(priorityFile);
    if (chunk && totalTokens + chunk.tokenCount <= maxTokens) {
      selected.push(chunk);
      totalTokens += chunk.tokenCount;
      candidates = candidates.filter((c) => c.id !== priorityFile);
    }
  }

  // Fill remaining budget
  for (const chunk of candidates) {
    if (selected.some((s) => s.id === chunk.id)) continue;

    if (totalTokens + chunk.tokenCount <= maxTokens) {
      selected.push(chunk);
      totalTokens += chunk.tokenCount;
    } else {
      excluded.push(chunk.id);
    }
  }

  const result: SelectionResult = {
    chunks: selected,
    totalTokens,
    budgetRemaining: maxTokens - totalTokens,
    excluded,
    stats: {
      filesConsidered: repoMap.chunks.size,
      filesSelected: selected.length,
      coveragePercent: (selected.length / repoMap.chunks.size) * 100,
      averageImportance:
        selected.reduce((sum, c) => sum + c.importance, 0) / selected.length || 0,
    },
  };

  deps.emit({
    type: 'selection.completed',
    selected: selected.length,
    budget: maxTokens,
  });

  return result;
}

// =============================================================================
// LSP-ENHANCED CONTEXT SELECTION
// =============================================================================

/**
 * Select relevant code with LSP-enhanced relevance scoring.
 */
export async function getEnhancedContext(
  deps: CodeSelectorDeps,
  options: EnhancedContextOptions,
): Promise<EnhancedContextResult> {
  const {
    editingFile,
    editingPosition,
    lspBoostFactor = 0.3,
    ...baseOptions
  } = options;

  // Start with base selection
  const baseResult = await selectRelevantCode(deps, baseOptions);

  // If no LSP or no editing file, return base result
  if (!deps.lspManager || !editingFile || !deps.hasActiveLSP()) {
    return {
      ...baseResult,
      lspEnhancements: null,
      lspBoostedFiles: [],
    };
  }

  // Gather LSP enhancements
  const enhancements = await gatherLSPEnhancements(deps, editingFile, editingPosition);

  // If no LSP data, return base result
  if (!enhancements.referencingFiles.length && !enhancements.referencedFiles.length) {
    return {
      ...baseResult,
      lspEnhancements: enhancements,
      lspBoostedFiles: [],
    };
  }

  // Re-select with LSP boosting
  const lspRelatedFiles = new Set([
    ...enhancements.referencingFiles,
    ...enhancements.referencedFiles,
  ]);

  // Get all chunks and apply LSP boost
  const repoMap = deps.repoMap!;
  const boostedFiles: string[] = [];

  const boostedChunks = Array.from(repoMap.chunks.values()).map(chunk => {
    const isLspRelated = lspRelatedFiles.has(chunk.filePath) ||
      lspRelatedFiles.has(chunk.id);

    if (isLspRelated) {
      boostedFiles.push(chunk.filePath);
      return {
        ...chunk,
        importance: Math.min(1, chunk.importance + lspBoostFactor),
      };
    }
    return chunk;
  });

  // Re-sort and select with boosted importance
  const candidates = boostedChunks.filter(chunk => {
    if (chunk.importance < (baseOptions.minImportance ?? 0)) return false;
    if (!baseOptions.includeTypes && chunk.type === 'types') return false;
    if (!baseOptions.includeTests && chunk.type === 'test') return false;
    return true;
  });

  // Calculate relevance if task provided
  const withRelevance = baseOptions.task
    ? candidates.map(chunk => ({
        ...chunk,
        relevance: calculateRelevance(chunk, baseOptions.task!),
      }))
    : candidates;

  // Sort and select within budget
  const sorted = sortByStrategy(
    withRelevance,
    baseOptions.strategy ?? 'importance_first',
    baseOptions.task,
  );

  const selected: CodeChunk[] = [];
  let totalTokens = 0;
  const excluded: string[] = [];

  // Prioritize editing file first
  if (editingFile) {
    const editingChunk = repoMap.chunks.get(editingFile);
    if (editingChunk && totalTokens + editingChunk.tokenCount <= baseOptions.maxTokens) {
      selected.push(editingChunk);
      totalTokens += editingChunk.tokenCount;
    }
  }

  // Then priority files
  for (const priorityFile of baseOptions.priorityFiles ?? []) {
    const chunk = repoMap.chunks.get(priorityFile);
    if (chunk && !selected.some(s => s.id === priorityFile)) {
      if (totalTokens + chunk.tokenCount <= baseOptions.maxTokens) {
        selected.push(chunk);
        totalTokens += chunk.tokenCount;
      }
    }
  }

  // Fill remaining budget
  for (const chunk of sorted) {
    if (selected.some(s => s.id === chunk.id)) continue;
    if (totalTokens + chunk.tokenCount <= baseOptions.maxTokens) {
      selected.push(chunk);
      totalTokens += chunk.tokenCount;
    } else {
      excluded.push(chunk.id);
    }
  }

  return {
    chunks: selected,
    totalTokens,
    budgetRemaining: baseOptions.maxTokens - totalTokens,
    excluded,
    stats: {
      filesConsidered: repoMap.chunks.size,
      filesSelected: selected.length,
      coveragePercent: (selected.length / repoMap.chunks.size) * 100,
      averageImportance: selected.reduce((sum, c) => sum + c.importance, 0) / selected.length || 0,
    },
    lspEnhancements: enhancements,
    lspBoostedFiles: boostedFiles.filter(f => selected.some(s => s.filePath === f)),
  };
}

/**
 * Gather LSP enhancements for a file.
 */
async function gatherLSPEnhancements(
  deps: CodeSelectorDeps,
  file: string,
  position?: SourcePosition,
): Promise<LSPEnhancements> {
  const enhancements: LSPEnhancements = {
    referencingFiles: [],
    referencedFiles: [],
  };

  if (!deps.lspManager) return enhancements;

  try {
    // Get references to symbols in this file
    // Use position if provided, otherwise check common export positions
    const checkPositions = position
      ? [position]
      : [
          { line: 0, character: 0 },
          { line: 10, character: 0 },
          { line: 20, character: 0 },
        ];

    const seenRefs = new Set<string>();
    for (const pos of checkPositions) {
      const refs = await deps.lspManager.getReferences(file, pos.line, pos.character, false);
      for (const ref of refs) {
        const refFile = uriToPath(ref.uri);
        if (refFile && refFile !== file && !seenRefs.has(refFile)) {
          seenRefs.add(refFile);
          enhancements.referencingFiles.push(refFile);
        }
      }
    }

    // Get definition to find what this file depends on
    if (position) {
      const def = await deps.lspManager.getDefinition(file, position.line, position.character);
      if (def) {
        const defFile = uriToPath(def.uri);
        if (defFile && defFile !== file) {
          enhancements.referencedFiles.push(defFile);

          // Get symbol info from hover
          const hover = await deps.lspManager.getHover(file, position.line, position.character);
          if (hover) {
            const symbolName = extractSymbolName(hover);
            if (symbolName) {
              enhancements.symbolAtCursor = {
                name: symbolName,
                definitionFile: defFile,
                referenceCount: enhancements.referencingFiles.length,
              };
            }
          }
        }
      }
    }

    // Also use the dependency graph from analyze() to supplement LSP data
    if (deps.repoMap) {
      const fileDeps = deps.repoMap.dependencyGraph.get(file);
      if (fileDeps) {
        for (const dep of fileDeps) {
          if (!enhancements.referencedFiles.includes(dep)) {
            enhancements.referencedFiles.push(dep);
          }
        }
      }

      const reverseDeps = deps.repoMap.reverseDependencyGraph.get(file);
      if (reverseDeps) {
        for (const dep of reverseDeps) {
          if (!enhancements.referencingFiles.includes(dep)) {
            enhancements.referencingFiles.push(dep);
          }
        }
      }
    }
  } catch {
    // LSP errors shouldn't break context selection
    // Just return what we have
  }

  return enhancements;
}

/**
 * Convert LSP URI to file path.
 */
function uriToPath(uri: string): string | null {
  if (uri.startsWith('file://')) {
    return uri.slice(7);
  }
  return uri;
}

/**
 * Extract symbol name from hover text.
 */
function extractSymbolName(hover: string): string | null {
  // Try to extract function/variable name from hover text
  // Common patterns: "function foo(...)", "const bar", "class Baz"
  const patterns = [
    /(?:function|const|let|var|class|interface|type)\s+(\w+)/,
    /^(\w+)\s*[:(]/,
    /^(\w+)\s*$/,
  ];

  for (const pattern of patterns) {
    const match = hover.match(pattern);
    if (match) return match[1];
  }

  return null;
}

// =============================================================================
// RELEVANCE SCORING
// =============================================================================

/**
 * Calculate task relevance for a chunk.
 */
export function calculateRelevance(chunk: CodeChunk, task: string): number {
  const taskLower = task.toLowerCase();
  const taskWords = taskLower.split(/\s+/).filter((w) => w.length > 2);

  let score = 0;

  // Check file path
  const pathLower = chunk.filePath.toLowerCase();
  for (const word of taskWords) {
    if (pathLower.includes(word)) {
      score += 0.3;
    }
  }

  // Check symbols
  for (const symbol of chunk.symbols) {
    const symbolLower = symbol.toLowerCase();
    for (const word of taskWords) {
      if (symbolLower.includes(word) || word.includes(symbolLower)) {
        score += 0.2;
      }
    }
  }

  // Check content (limited to avoid expensive full-text search)
  const contentSample = chunk.content.slice(0, 2000).toLowerCase();
  for (const word of taskWords) {
    if (contentSample.includes(word)) {
      score += 0.1;
    }
  }

  return Math.min(1, score);
}

/**
 * Sort candidates by selection strategy.
 */
export function sortByStrategy(
  candidates: (CodeChunk & { relevance?: number })[],
  strategy: SelectionStrategy,
  task?: string,
): CodeChunk[] {
  switch (strategy) {
    case 'importance_first':
      return candidates.sort((a, b) => b.importance - a.importance);

    case 'relevance_first':
      if (!task) return sortByStrategy(candidates, 'importance_first');
      return candidates.sort((a, b) => {
        const relDiff = (b.relevance ?? 0) - (a.relevance ?? 0);
        if (Math.abs(relDiff) > 0.1) return relDiff;
        return b.importance - a.importance;
      });

    case 'breadth_first': {
      // Group by directory, pick one from each, then repeat
      const byDir = new Map<string, CodeChunk[]>();
      for (const chunk of candidates) {
        const dir = path.dirname(chunk.filePath);
        if (!byDir.has(dir)) byDir.set(dir, []);
        byDir.get(dir)!.push(chunk);
      }

      // Sort each directory's files by importance
      for (const files of byDir.values()) {
        files.sort((a, b) => b.importance - a.importance);
      }

      // Interleave
      const result: CodeChunk[] = [];
      let hasMore = true;
      let index = 0;
      while (hasMore) {
        hasMore = false;
        for (const files of byDir.values()) {
          if (index < files.length) {
            result.push(files[index]);
            hasMore = true;
          }
        }
        index++;
      }
      return result;
    }

    case 'depth_first':
      // Start with entry points, then follow dependencies
      return candidates.sort((a, b) => {
        // Entry points first
        if (a.type === 'entry_point' && b.type !== 'entry_point') return -1;
        if (b.type === 'entry_point' && a.type !== 'entry_point') return 1;
        // Then by importance
        return b.importance - a.importance;
      });

    default:
      return candidates;
  }
}

// =============================================================================
// INCREMENTAL EXPANSION
// =============================================================================

/**
 * Expand context by adding related files to current selection.
 */
export async function expandContext(
  deps: CodeSelectorDeps,
  currentChunks: CodeChunk[],
  options: {
    maxTokensToAdd: number;
    direction: 'dependencies' | 'dependents' | 'both';
    query?: string;
  },
): Promise<CodeChunk[]> {
  if (!deps.repoMap) {
    await deps.analyze();
  }

  const repoMap = deps.repoMap!;
  const currentIds = new Set(currentChunks.map((c) => c.id));
  const candidates: CodeChunk[] = [];

  for (const chunk of currentChunks) {
    // Get dependencies
    if (options.direction === 'dependencies' || options.direction === 'both') {
      const fileDeps = repoMap.dependencyGraph.get(chunk.filePath);
      if (fileDeps) {
        for (const dep of fileDeps) {
          if (!currentIds.has(dep)) {
            const depChunk = repoMap.chunks.get(dep);
            if (depChunk) {
              candidates.push(depChunk);
              currentIds.add(dep);
            }
          }
        }
      }
    }

    // Get dependents
    if (options.direction === 'dependents' || options.direction === 'both') {
      const dependents = repoMap.reverseDependencyGraph.get(chunk.filePath);
      if (dependents) {
        for (const dep of dependents) {
          if (!currentIds.has(dep)) {
            const depChunk = repoMap.chunks.get(dep);
            if (depChunk) {
              candidates.push(depChunk);
              currentIds.add(dep);
            }
          }
        }
      }
    }
  }

  // Filter by query if provided
  let filtered = candidates;
  if (options.query) {
    filtered = candidates.filter((c) => calculateRelevance(c, options.query!) > 0);
  }

  // Sort by importance and select within budget
  filtered.sort((a, b) => b.importance - a.importance);

  const toAdd: CodeChunk[] = [];
  let addedTokens = 0;

  for (const chunk of filtered) {
    if (addedTokens + chunk.tokenCount <= options.maxTokensToAdd) {
      toAdd.push(chunk);
      addedTokens += chunk.tokenCount;
    }
  }

  return toAdd;
}

// =============================================================================
// SEARCH
// =============================================================================

/**
 * Search for code chunks matching a query.
 */
export function searchChunks(
  repoMap: RepoMap | null,
  query: string,
  options: SearchOptions = {},
): CodeChunk[] {
  const {
    includeSymbols = true,
    includePaths = true,
    includeContent = false,
    caseSensitive = false,
    fuzzyMatch: useFuzzy = false,
    maxDistance = 2,
  } = options;

  if (!repoMap) return [];

  const queryTerms = tokenizeQuery(query);
  if (queryTerms.length === 0) return [];

  const normalize = caseSensitive
    ? (s: string) => s
    : (s: string) => s.toLowerCase();

  const chunks = Array.from(repoMap.chunks.values());

  return chunks.filter(chunk => {
    // Symbol matching (most relevant for code search)
    if (includeSymbols && chunk.symbols.length > 0) {
      const symbolMatch = chunk.symbols.some(symbol => {
        const normalizedSymbol = normalize(symbol);
        return queryTerms.some(term => {
          if (useFuzzy) {
            return fuzzyMatch(normalizedSymbol, normalize(term), maxDistance);
          }
          return normalizedSymbol.includes(normalize(term));
        });
      });
      if (symbolMatch) return true;
    }

    // Path matching
    if (includePaths) {
      const normalizedPath = normalize(chunk.filePath);
      const pathMatch = queryTerms.some(term => {
        const normalizedTerm = normalize(term);
        // Always check substring first
        if (normalizedPath.includes(normalizedTerm)) {
          return true;
        }
        // Additionally check fuzzy match on filename if enabled
        if (useFuzzy) {
          const filename = path.basename(chunk.filePath, path.extname(chunk.filePath));
          return fuzzyMatch(normalize(filename), normalizedTerm, maxDistance);
        }
        return false;
      });
      if (pathMatch) return true;
    }

    // Content matching (expensive, off by default)
    if (includeContent) {
      const normalizedContent = normalize(chunk.content);
      const contentMatch = queryTerms.every(term =>
        normalizedContent.includes(normalize(term)),
      );
      if (contentMatch) return true;
    }

    return false;
  });
}

/**
 * Search and rank results by relevance.
 */
export function searchRanked(
  repoMap: RepoMap | null,
  query: string,
  options: RankedSearchOptions = {},
): ScoredChunk[] {
  const { limit, ...searchOptions } = options;

  const matches = searchChunks(repoMap, query, searchOptions);

  const scored = matches.map(chunk => ({
    chunk,
    score: calculateSearchScore(chunk, query),
  }));

  scored.sort((a, b) => b.score - a.score);

  if (limit && limit > 0) {
    return scored.slice(0, limit);
  }

  return scored;
}

/**
 * Calculate relevance score for a chunk given a search query.
 */
export function calculateSearchScore(chunk: CodeChunk, query: string): number {
  const queryLower = query.toLowerCase();
  const queryTerms = tokenizeQuery(query);
  let score = chunk.importance * 10; // Base score from importance

  // Boost for exact symbol name match
  for (const symbol of chunk.symbols) {
    const symbolLower = symbol.toLowerCase();
    if (symbolLower === queryLower) {
      score += 50; // Exact match
    } else if (symbolLower.includes(queryLower)) {
      score += 20; // Partial match
    } else {
      // Check individual terms
      for (const term of queryTerms) {
        if (symbolLower.includes(term.toLowerCase())) {
          score += 10;
        }
      }
    }
  }

  // Boost for file name match
  const filename = path.basename(chunk.filePath).toLowerCase();
  if (filename.includes(queryLower)) {
    score += 15;
  } else {
    for (const term of queryTerms) {
      if (filename.includes(term.toLowerCase())) {
        score += 5;
      }
    }
  }

  // Boost for entry points and core modules
  if (chunk.type === 'entry_point') {
    score += 10;
  } else if (chunk.type === 'core_module') {
    score += 5;
  }

  // Small boost for path matches
  const pathLower = chunk.filePath.toLowerCase();
  for (const term of queryTerms) {
    if (pathLower.includes(term.toLowerCase())) {
      score += 2;
    }
  }

  return score;
}

// =============================================================================
// STRING UTILITIES
// =============================================================================

/**
 * Tokenize a search query into terms.
 */
export function tokenizeQuery(query: string): string[] {
  // Common stop words to filter out
  const stopWords = new Set([
    'the', 'and', 'for', 'with', 'this', 'that', 'from', 'are', 'was', 'were',
    'been', 'being', 'have', 'has', 'had', 'does', 'did', 'will', 'would',
    'could', 'should', 'may', 'might', 'must', 'can',
  ]);

  return query
    .split(/\s+/)
    .map(term => term.replace(/[^\w]/g, '')) // Remove punctuation
    .filter(term => term.length > 1) // At least 2 chars
    .filter(term => !stopWords.has(term.toLowerCase()));
}

/**
 * Fuzzy match two strings using Levenshtein distance.
 */
export function fuzzyMatch(a: string, b: string, maxDistance: number): boolean {
  // Quick length check
  if (Math.abs(a.length - b.length) > maxDistance) return false;

  // If one contains the other, it's a match
  if (a.includes(b) || b.includes(a)) return true;

  // Compute Levenshtein distance
  const distance = levenshteinDistance(a, b);
  return distance <= maxDistance;
}

/**
 * Compute Levenshtein distance between two strings.
 */
export function levenshteinDistance(a: string, b: string): number {
  if (a.length === 0) return b.length;
  if (b.length === 0) return a.length;

  // Use two-row optimization for memory efficiency
  let previousRow = Array.from({ length: b.length + 1 }, (_, i) => i);
  let currentRow = new Array(b.length + 1);

  for (let i = 0; i < a.length; i++) {
    currentRow[0] = i + 1;

    for (let j = 0; j < b.length; j++) {
      const insertCost = currentRow[j] + 1;
      const deleteCost = previousRow[j + 1] + 1;
      const replaceCost = previousRow[j] + (a[i] === b[j] ? 0 : 1);

      currentRow[j + 1] = Math.min(insertCost, deleteCost, replaceCost);
    }

    [previousRow, currentRow] = [currentRow, previousRow];
  }

  return previousRow[b.length];
}
