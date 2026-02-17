/**
 * Codebase Context Integration
 *
 * Provides intelligent code selection for context management.
 * Analyzes repository structure and selects relevant code based on:
 * - Task relevance (semantic matching)
 * - Architectural importance (entry points, core modules)
 * - Token budget constraints
 *
 * Key features:
 * - Budget-aware context building (select code that fits)
 * - Importance scoring (imports, exports, modification frequency)
 * - Incremental expansion (start minimal, expand as needed)
 * - Semantic relevance matching (keyword + structure analysis)
 *
 * Implementation split (Phase 3d):
 * - code-analyzer.ts  — AST + dependency analysis helpers
 * - code-selector.ts  — Token-budget selection + ranking
 * - codebase-context.ts — Main manager class + types + factory functions (this file)
 */

import * as path from 'path';
import type { LSPManager } from '../lsp/lsp.js';
import type { TraceCollector } from '../../tracing/trace-collector.js';

// Analyzer functions (file discovery, processing, dependency analysis)
import {
  discoverFiles,
  processFile,
  extractDependencies,
  adjustImportanceByConnectivity,
  matchesPatterns,
  type CodeAnalyzerDeps,
} from './code-analyzer.js';

import { clearASTCache, fullReparse, djb2Hash } from './codebase-ast.js';
import type { SavedCodebaseAnalysis } from '../persistence/codebase-repository.js';

// Selector functions (selection, search, ranking, LSP-enhanced context)
import {
  selectRelevantCode as selectRelevantCodeImpl,
  getEnhancedContext as getEnhancedContextImpl,
  expandContext as expandContextImpl,
  searchChunks,
  searchRanked as searchRankedImpl,
  type CodeSelectorDeps,
} from './code-selector.js';

// Re-export extracted modules for direct consumer access
export {
  type CodeAnalyzerDeps,
  discoverFiles,
  processFile,
  extractDependencies,
  adjustImportanceByConnectivity,
  matchesPatterns,
  matchesGlob,
  normalizePath,
  determineChunkType,
  calculateBaseImportance,
  extractSymbols,
  extractSymbolDetails,
  extractDependencyNames,
} from './code-analyzer.js';

export {
  type CodeSelectorDeps,
  selectRelevantCode as selectRelevantCodeFn,
  getEnhancedContext as getEnhancedContextFn,
  expandContext as expandContextFn,
  searchChunks,
  searchRanked as searchRankedFn,
  calculateRelevance,
  calculateSearchScore,
  sortByStrategy,
  tokenizeQuery,
  fuzzyMatch,
  levenshteinDistance,
} from './code-selector.js';

// =============================================================================
// TYPES
// =============================================================================

/**
 * A chunk of code with metadata for context selection.
 */
export interface CodeChunk {
  /** Unique identifier */
  id: string;
  /** Relative file path from repo root */
  filePath: string;
  /** The actual code content */
  content: string;
  /** Estimated token count */
  tokenCount: number;
  /** Importance score (0-1) */
  importance: number;
  /** Type of code chunk */
  type: CodeChunkType;
  /** Symbols defined in this chunk */
  symbols: string[];
  /** Structured symbols for visualization and tracing */
  symbolDetails: Array<{ name: string; kind: string; exported: boolean; line: number }>;
  /** Symbols imported/used by this chunk */
  dependencies: string[];
  /** Last modified timestamp */
  lastModified?: Date;
}

export type CodeChunkType =
  | 'entry_point' // Main entry points (index.ts, main.ts, app.ts)
  | 'core_module' // Core business logic
  | 'utility' // Utility/helper functions
  | 'types' // Type definitions
  | 'config' // Configuration files
  | 'test' // Test files
  | 'documentation' // Markdown, comments
  | 'other';

/**
 * Repository structure map.
 */
export interface RepoMap {
  /** Root directory of the repo */
  root: string;
  /** All discovered code chunks */
  chunks: Map<string, CodeChunk>;
  /** Entry point files */
  entryPoints: string[];
  /** Core module directories */
  coreModules: string[];
  /** Dependency graph (file -> imported files) */
  dependencyGraph: Map<string, Set<string>>;
  /** Reverse dependency graph (file -> files that import it) */
  reverseDependencyGraph: Map<string, Set<string>>;
  /** Total estimated tokens */
  totalTokens: number;
  /** Analysis timestamp */
  analyzedAt: Date;
}

/**
 * Configuration for codebase context.
 */
export interface CodebaseContextConfig {
  /** Root directory to analyze */
  root?: string;
  /** File patterns to include (glob) */
  includePatterns?: string[];
  /** File patterns to exclude (glob) */
  excludePatterns?: string[];
  /** Maximum file size in bytes */
  maxFileSize?: number;
  /** Estimate tokens per character ratio */
  tokensPerChar?: number;
  /** Entry point file patterns */
  entryPointPatterns?: string[];
  /** Core module directory patterns */
  coreModulePatterns?: string[];
  /** Enable dependency graph analysis */
  analyzeDependencies?: boolean;
  /** Cache analysis results */
  cacheResults?: boolean;
  /** Cache TTL in milliseconds */
  cacheTTL?: number;
}

/**
 * Options for selecting relevant code.
 */
export interface SelectionOptions {
  /** Maximum token budget */
  maxTokens: number;
  /** Task description for relevance scoring */
  task?: string;
  /** Specific files to prioritize */
  priorityFiles?: string[];
  /** Minimum importance threshold */
  minImportance?: number;
  /** Include types/interfaces */
  includeTypes?: boolean;
  /** Include tests */
  includeTests?: boolean;
  /** Strategy for selection */
  strategy?: SelectionStrategy;
}

export type SelectionStrategy =
  | 'importance_first' // Select by importance, then fit to budget
  | 'relevance_first' // Select by task relevance, then fit
  | 'breadth_first' // Select diverse files first
  | 'depth_first'; // Select related files deeply

/**
 * Result of code selection.
 */
export interface SelectionResult {
  /** Selected code chunks */
  chunks: CodeChunk[];
  /** Total tokens used */
  totalTokens: number;
  /** Budget remaining */
  budgetRemaining: number;
  /** Files that were excluded due to budget */
  excluded: string[];
  /** Selection statistics */
  stats: {
    filesConsidered: number;
    filesSelected: number;
    coveragePercent: number;
    averageImportance: number;
  };
}

/**
 * Events emitted by the codebase context manager.
 */
export type CodebaseContextEvent =
  | { type: 'analysis.started'; root: string }
  | { type: 'analysis.completed'; totalFiles: number; totalTokens: number }
  | { type: 'analysis.error'; error: Error }
  | { type: 'selection.completed'; selected: number; budget: number }
  | { type: 'cache.hit'; root: string }
  | { type: 'cache.miss'; root: string };

export type CodebaseContextEventListener = (event: CodebaseContextEvent) => void;

/**
 * Minimal interface for codebase analysis persistence.
 * Implemented by SQLiteStore.
 */
export interface CodebasePersistenceStore {
  saveCodebaseAnalysis(
    root: string,
    chunks: Iterable<{
      filePath: string;
      content: string;
      symbolDetails: Array<{ name: string; kind: string; exported: boolean; line: number }>;
      dependencies: string[];
      importance: number;
      type: string;
      tokenCount: number;
    }>,
    dependencyGraph: Map<string, Set<string>>,
  ): void;
  loadCodebaseAnalysis(root: string): SavedCodebaseAnalysis | null;
}

/**
 * Position in a source file.
 */
export interface SourcePosition {
  line: number;
  character: number;
}

/**
 * LSP enhancements for context selection.
 */
export interface LSPEnhancements {
  /** Files that reference the editing file */
  referencingFiles: string[];
  /** Files that the editing file references */
  referencedFiles: string[];
  /** Symbols found at cursor position */
  symbolAtCursor?: {
    name: string;
    definitionFile?: string;
    referenceCount: number;
  };
}

/**
 * Options for LSP-enhanced context selection.
 */
export interface EnhancedContextOptions extends SelectionOptions {
  /** File currently being edited */
  editingFile?: string;
  /** Cursor position in editing file */
  editingPosition?: SourcePosition;
  /** Boost factor for LSP-related files (0-1, default 0.3) */
  lspBoostFactor?: number;
}

/**
 * Result of LSP-enhanced context selection.
 */
export interface EnhancedContextResult extends SelectionResult {
  /** LSP enhancements applied, if any */
  lspEnhancements: LSPEnhancements | null;
  /** Files that were boosted due to LSP relationships */
  lspBoostedFiles: string[];
}

/**
 * Options for searching code chunks.
 */
export interface SearchOptions {
  /** Search in symbol names (function, class, variable names) */
  includeSymbols?: boolean;
  /** Search in file paths */
  includePaths?: boolean;
  /** Search in file content (expensive) */
  includeContent?: boolean;
  /** Case-sensitive matching */
  caseSensitive?: boolean;
  /** Enable fuzzy matching for typos */
  fuzzyMatch?: boolean;
  /** Maximum edit distance for fuzzy matching (default: 2) */
  maxDistance?: number;
}

/**
 * Options for ranked search.
 */
export interface RankedSearchOptions extends SearchOptions {
  /** Maximum number of results to return */
  limit?: number;
}

/**
 * A code chunk with a relevance score.
 */
export interface ScoredChunk {
  chunk: CodeChunk;
  score: number;
}

// =============================================================================
// CONSTANTS
// =============================================================================

const DEFAULT_CONFIG: Required<CodebaseContextConfig> = {
  root: process.cwd(),
  includePatterns: ['**/*.ts', '**/*.tsx', '**/*.js', '**/*.jsx', '**/*.py', '**/*.go', '**/*.rs'],
  excludePatterns: [
    '**/node_modules/**',
    '**/dist/**',
    '**/build/**',
    '**/.git/**',
    '**/coverage/**',
    '**/__pycache__/**',
    '**/target/**',
    '**/vendor/**',
  ],
  maxFileSize: 100 * 1024, // 100KB
  tokensPerChar: 0.25, // Approximate: 4 chars per token
  entryPointPatterns: [
    '**/index.ts',
    '**/index.tsx',
    '**/index.js',
    '**/main.ts',
    '**/main.py',
    '**/main.go',
    '**/app.ts',
    '**/app.tsx',
    '**/app.py',
    '**/server.ts',
    '**/server.js',
    '**/cli.ts',
    '**/cli.js',
  ],
  coreModulePatterns: ['**/src/**', '**/lib/**', '**/core/**', '**/services/**', '**/modules/**'],
  analyzeDependencies: true,
  cacheResults: true,
  cacheTTL: 5 * 60 * 1000, // 5 minutes
};

// =============================================================================
// CODEBASE CONTEXT MANAGER
// =============================================================================

/**
 * Manages intelligent code selection for context building.
 *
 * @example
 * ```typescript
 * const codebase = createCodebaseContext({ root: './my-project' });
 *
 * // Analyze the repository
 * const repoMap = await codebase.analyze();
 *
 * // Select relevant code for a task within budget
 * const selection = await codebase.selectRelevantCode({
 *   task: 'implement user authentication',
 *   maxTokens: 8000,
 *   strategy: 'relevance_first',
 * });
 *
 * // Use selected code in context
 * const context = selection.chunks.map(c => c.content).join('\n\n');
 * ```
 */
export class CodebaseContextManager {
  private config: Required<CodebaseContextConfig>;
  private repoMap: RepoMap | null = null;
  private cache: Map<string, { map: RepoMap; expires: number }> = new Map();
  private listeners: CodebaseContextEventListener[] = [];
  private lspManager: LSPManager | null = null;

  /** Optional trace collector for emitting codebase analysis events. */
  traceCollector?: TraceCollector;

  /** Optional store for persisting codebase analysis across sessions. */
  private persistenceStore: CodebasePersistenceStore | null = null;

  constructor(config: CodebaseContextConfig = {}) {
    this.config = { ...DEFAULT_CONFIG, ...config };
  }

  /**
   * Set the persistence store for warm startup across sessions.
   * Accepts any object implementing saveCodebaseAnalysis/loadCodebaseAnalysis (e.g. SQLiteStore).
   */
  setPersistenceStore(store: CodebasePersistenceStore): void {
    this.persistenceStore = store;
  }

  /**
   * Set the LSP manager for enhanced context selection.
   * When set, context selection can use LSP for more accurate relevance scoring.
   */
  setLSPManager(lsp: LSPManager): void {
    this.lspManager = lsp;
  }

  /**
   * Get the current LSP manager, if any.
   */
  getLSPManager(): LSPManager | null {
    return this.lspManager;
  }

  /**
   * Check if LSP is available and active.
   */
  hasActiveLSP(): boolean {
    if (!this.lspManager) return false;
    const servers = this.lspManager.getActiveServers();
    return servers.length > 0;
  }

  // ===========================================================================
  // ANALYSIS
  // ===========================================================================

  /**
   * Analyze a repository and build its structure map.
   */
  async analyze(root?: string): Promise<RepoMap> {
    const repoRoot = root ?? this.config.root;

    this.emit({ type: 'analysis.started', root: repoRoot });

    // Check cache
    if (this.config.cacheResults) {
      const cached = this.cache.get(repoRoot);
      if (cached && cached.expires > Date.now()) {
        this.emit({ type: 'cache.hit', root: repoRoot });
        this.repoMap = cached.map;
        return cached.map;
      }
      this.emit({ type: 'cache.miss', root: repoRoot });
    }

    try {
      const chunks = new Map<string, CodeChunk>();
      const entryPoints: string[] = [];
      const coreModules: string[] = [];
      const dependencyGraph = new Map<string, Set<string>>();
      const reverseDependencyGraph = new Map<string, Set<string>>();

      const analyzerDeps = this as unknown as CodeAnalyzerDeps;

      // Discover files
      const files = await discoverFiles(analyzerDeps, repoRoot);

      // Warm startup: try loading persisted analysis and only reprocess changed files
      const savedAnalysis = this.persistenceStore
        ? this.persistenceStore.loadCodebaseAnalysis(repoRoot)
        : null;
      const filesToProcess = savedAnalysis
        ? await this.diffAgainstSaved(repoRoot, files, savedAnalysis, chunks)
        : files;

      // Process each file (only changed/new files when warm-starting)
      for (const filePath of filesToProcess) {
        const chunk = await processFile(analyzerDeps, repoRoot, filePath);
        if (chunk) {
          chunks.set(chunk.id, chunk);

          // Track entry points
          if (chunk.type === 'entry_point') {
            entryPoints.push(filePath);
          }

          // Build dependency graph
          if (this.config.analyzeDependencies) {
            const fullPath = path.join(repoRoot, filePath);
            const deps = extractDependencies(chunk.content, fullPath);
            dependencyGraph.set(filePath, deps);

            // Build reverse graph
            for (const dep of deps) {
              if (!reverseDependencyGraph.has(dep)) {
                reverseDependencyGraph.set(dep, new Set());
              }
              reverseDependencyGraph.get(dep)!.add(filePath);
            }
          }
        }
      }

      // Restore dependency graph edges for unchanged files from saved analysis
      if (savedAnalysis && this.config.analyzeDependencies) {
        for (const [source, targets] of savedAnalysis.deps) {
          if (!filesToProcess.includes(source) && chunks.has(source)) {
            dependencyGraph.set(source, targets);
            for (const dep of targets) {
              if (!reverseDependencyGraph.has(dep)) {
                reverseDependencyGraph.set(dep, new Set());
              }
              reverseDependencyGraph.get(dep)!.add(source);
            }
          }
        }
      }

      // Ensure entry points include restored unchanged files
      if (savedAnalysis) {
        for (const [filePath, chunk] of chunks) {
          if (chunk.type === 'entry_point' && !entryPoints.includes(filePath)) {
            entryPoints.push(filePath);
          }
        }
      }

      // Calculate total tokens
      let totalTokens = 0;
      for (const chunk of chunks.values()) {
        totalTokens += chunk.tokenCount;
      }

      // Adjust importance based on dependency graph
      adjustImportanceByConnectivity(chunks, reverseDependencyGraph);

      // Identify core modules
      const moduleDirs = new Set<string>();
      for (const filePath of files) {
        const dir = path.dirname(filePath);
        if (matchesPatterns(analyzerDeps, dir, this.config.coreModulePatterns)) {
          moduleDirs.add(dir);
        }
      }
      coreModules.push(...moduleDirs);

      const repoMap: RepoMap = {
        root: repoRoot,
        chunks,
        entryPoints,
        coreModules,
        dependencyGraph,
        reverseDependencyGraph,
        totalTokens,
        analyzedAt: new Date(),
      };

      // Cache result
      if (this.config.cacheResults) {
        this.cache.set(repoRoot, {
          map: repoMap,
          expires: Date.now() + this.config.cacheTTL,
        });
      }

      this.repoMap = repoMap;

      // Persist analysis to SQLite for warm startup next session
      if (this.persistenceStore) {
        try {
          this.persistenceStore.saveCodebaseAnalysis(repoRoot, chunks.values(), dependencyGraph);
        } catch {
          /* persistence is non-blocking */
        }
      }

      this.emit({
        type: 'analysis.completed',
        totalFiles: chunks.size,
        totalTokens,
      });

      // Emit trace event with full codebase map data
      this.traceCollector?.record({
        type: 'codebase.map',
        data: {
          totalFiles: chunks.size,
          totalTokens,
          entryPoints,
          coreModules,
          dependencyEdges: Array.from(dependencyGraph.entries()).map(([file, imports]) => ({
            file,
            imports: Array.from(imports),
          })),
          topChunks: Array.from(chunks.values())
            .sort((a, b) => b.importance - a.importance)
            .slice(0, 50)
            .map((chunk) => ({
              filePath: chunk.filePath,
              tokenCount: chunk.tokenCount,
              importance: chunk.importance,
              type: chunk.type,
              symbols: chunk.symbolDetails,
              dependencies: chunk.dependencies,
            })),
          files: Array.from(chunks.values()).map((chunk) => ({
            filePath: chunk.filePath,
            directory: path.dirname(chunk.filePath) === '.' ? '' : path.dirname(chunk.filePath),
            fileName: path.basename(chunk.filePath),
            tokenCount: chunk.tokenCount,
            importance: chunk.importance,
            type: chunk.type,
            symbols: chunk.symbolDetails,
            inDegree: reverseDependencyGraph.get(chunk.filePath)?.size ?? 0,
            outDegree: dependencyGraph.get(chunk.filePath)?.size ?? 0,
          })),
        },
      });

      return repoMap;
    } catch (error) {
      this.emit({ type: 'analysis.error', error: error as Error });
      throw error;
    }
  }

  // ===========================================================================
  // SELECTION (delegates to code-selector.ts)
  // ===========================================================================

  /**
   * Select relevant code chunks for a task within a token budget.
   */
  async selectRelevantCode(options: SelectionOptions): Promise<SelectionResult> {
    return selectRelevantCodeImpl(this.asSelectorDeps(), options);
  }

  // ===========================================================================
  // LSP-ENHANCED CONTEXT SELECTION (delegates to code-selector.ts)
  // ===========================================================================

  /**
   * Select relevant code with LSP-enhanced relevance scoring.
   *
   * When an LSP manager is set and active, this method uses LSP to:
   * - Find files that reference the editing file (who uses this code?)
   * - Find files that the editing file references (what does this depend on?)
   * - Boost priority of related files in the selection
   *
   * @example
   * ```typescript
   * const codebase = createCodebaseContext({ root: './project' });
   * codebase.setLSPManager(lspManager);
   *
   * const result = await codebase.getEnhancedContext({
   *   task: 'fix bug in authentication',
   *   maxTokens: 10000,
   *   editingFile: 'src/auth/login.ts',
   *   editingPosition: { line: 25, character: 10 },
   * });
   *
   * // Result includes LSP-boosted files
   * console.log('LSP boosted:', result.lspBoostedFiles);
   * ```
   */
  async getEnhancedContext(options: EnhancedContextOptions): Promise<EnhancedContextResult> {
    return getEnhancedContextImpl(this.asSelectorDeps(), options);
  }

  // ===========================================================================
  // INCREMENTAL EXPANSION (delegates to code-selector.ts)
  // ===========================================================================

  /**
   * Expand context by adding related files to current selection.
   */
  async expandContext(
    currentChunks: CodeChunk[],
    options: {
      maxTokensToAdd: number;
      direction: 'dependencies' | 'dependents' | 'both';
      query?: string;
    },
  ): Promise<CodeChunk[]> {
    return expandContextImpl(this.asSelectorDeps(), currentChunks, options);
  }

  // ===========================================================================
  // UTILITIES
  // ===========================================================================

  /**
   * Get a chunk by file path.
   */
  getChunk(filePath: string): CodeChunk | undefined {
    return this.repoMap?.chunks.get(filePath);
  }

  /**
   * Get all chunks.
   */
  getAllChunks(): CodeChunk[] {
    return this.repoMap ? Array.from(this.repoMap.chunks.values()) : [];
  }

  /**
   * Get entry points.
   */
  getEntryPoints(): CodeChunk[] {
    if (!this.repoMap) return [];
    return this.repoMap.entryPoints
      .map((ep) => this.repoMap!.chunks.get(ep))
      .filter((c): c is CodeChunk => c !== undefined);
  }

  /**
   * Estimate tokens for a string.
   */
  estimateTokens(content: string): number {
    return Math.ceil(content.length * this.config.tokensPerChar);
  }

  /**
   * Get the current repo map.
   */
  getRepoMap(): RepoMap | null {
    return this.repoMap;
  }

  /**
   * Clear cached data (including AST parse cache).
   */
  clearCache(): void {
    this.cache.clear();
    this.repoMap = null;
    clearASTCache();
  }

  // ===========================================================================
  // WARM STARTUP HELPERS (Phase 3)
  // ===========================================================================

  /**
   * Diff discovered files against saved analysis.
   * Reuses saved chunks for unchanged files, returns only files that need reprocessing.
   */
  private async diffAgainstSaved(
    repoRoot: string,
    files: string[],
    saved: SavedCodebaseAnalysis,
    chunks: Map<string, CodeChunk>,
  ): Promise<string[]> {
    const { default: fs } = await import('fs/promises');
    const changedFiles: string[] = [];

    for (const relativePath of files) {
      const savedChunk = saved.chunks.get(relativePath);
      if (savedChunk) {
        // Check if file content has changed by reading + hashing
        try {
          const fullPath = path.join(repoRoot, relativePath);
          const content = await fs.readFile(fullPath, 'utf-8');
          const currentHash = djb2Hash(content).toString(36);
          if (currentHash === savedChunk.contentHash) {
            // Unchanged — restore chunk from saved data
            const symbolDetails = JSON.parse(savedChunk.symbolsJson || '[]');
            const dependencies = JSON.parse(savedChunk.dependenciesJson || '[]');
            chunks.set(relativePath, {
              id: relativePath,
              filePath: relativePath,
              content,
              tokenCount: savedChunk.tokenCount,
              importance: savedChunk.importance,
              type: savedChunk.chunkType as CodeChunkType,
              symbols: symbolDetails.map((s: { name: string }) => s.name),
              symbolDetails,
              dependencies,
              lastModified: new Date(savedChunk.analyzedAt),
            });
            continue;
          }
        } catch {
          // File read failed — treat as changed
        }
      }
      changedFiles.push(relativePath);
    }

    return changedFiles;
  }

  // ===========================================================================
  // INCREMENTAL FILE UPDATES (Phase 2)
  // ===========================================================================

  /**
   * Update a single file's chunk in-place after an edit.
   * Reparses the file, patches the chunk's symbols/deps, and updates dependency graph edges.
   * Avoids full re-analyze for single-file edits.
   */
  async updateFile(filePath: string, newContent: string): Promise<void> {
    if (!this.repoMap) return;

    const relativePath = path.relative(this.config.root, filePath);
    const parsed = fullReparse(filePath, newContent);
    const existingChunk = this.repoMap.chunks.get(relativePath);

    if (existingChunk) {
      // Patch in-place
      existingChunk.content = newContent;
      existingChunk.tokenCount = Math.ceil(newContent.length * this.config.tokensPerChar);
      existingChunk.lastModified = new Date();
      if (parsed) {
        existingChunk.symbols = parsed.symbols.map((s) => s.name);
        existingChunk.symbolDetails = parsed.symbols.map((s) => ({
          name: s.name,
          kind: s.kind,
          exported: s.exported,
          line: s.line,
        }));
        existingChunk.dependencies = parsed.dependencies.flatMap((d) =>
          d.names.filter((n) => !n.startsWith('* as ')),
        );
      }

      // Update dependency graph edges for this file
      this.updateDependencyEdges(relativePath, newContent);

      // Recalculate total tokens
      let totalTokens = 0;
      for (const chunk of this.repoMap.chunks.values()) {
        totalTokens += chunk.tokenCount;
      }
      this.repoMap.totalTokens = totalTokens;
    }
    // New files (not in chunks) require a full re-analyze
  }

  private updateDependencyEdges(filePath: string, content: string): void {
    if (!this.repoMap) return;
    const { dependencyGraph, reverseDependencyGraph } = this.repoMap;

    // Remove old forward edges
    const oldDeps = dependencyGraph.get(filePath);
    if (oldDeps) {
      for (const dep of oldDeps) {
        reverseDependencyGraph.get(dep)?.delete(filePath);
      }
    }

    // Build new forward edges (use absolute path for AST cache lookup)
    const fullPath = path.join(this.config.root, filePath);
    const newDeps = extractDependencies(content, fullPath);
    dependencyGraph.set(filePath, newDeps);

    // Build new reverse edges
    for (const dep of newDeps) {
      if (!reverseDependencyGraph.has(dep)) {
        reverseDependencyGraph.set(dep, new Set());
      }
      reverseDependencyGraph.get(dep)!.add(filePath);
    }
  }

  /**
   * Subscribe to events.
   */
  on(listener: CodebaseContextEventListener): () => void {
    this.listeners.push(listener);
    return () => {
      const idx = this.listeners.indexOf(listener);
      if (idx >= 0) this.listeners.splice(idx, 1);
    };
  }

  private emit(event: CodebaseContextEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch {
        // Ignore listener errors
      }
    }
  }

  // ===========================================================================
  // ENHANCED SEARCH (delegates to code-selector.ts)
  // ===========================================================================

  /**
   * Search for code chunks matching a query.
   *
   * @example
   * ```typescript
   * const results = codebase.search('authentication', {
   *   includeSymbols: true,
   *   includePaths: true,
   * });
   * ```
   */
  search(query: string, options: SearchOptions = {}): CodeChunk[] {
    return searchChunks(this.repoMap, query, options);
  }

  /**
   * Search and rank results by relevance.
   *
   * @example
   * ```typescript
   * const ranked = codebase.searchRanked('user auth', { limit: 10 });
   * ranked.forEach(r => console.log(`${r.chunk.filePath}: ${r.score}`));
   * ```
   */
  searchRanked(query: string, options: RankedSearchOptions = {}): ScoredChunk[] {
    return searchRankedImpl(this.repoMap, query, options);
  }

  // ===========================================================================
  // INTERNAL HELPERS
  // ===========================================================================

  /**
   * Build the CodeSelectorDeps facade for delegating to code-selector functions.
   */
  private asSelectorDeps(): CodeSelectorDeps {
    // eslint-disable-next-line @typescript-eslint/no-this-alias
    const self = this;
    return {
      get repoMap() {
        return self.repoMap;
      },
      get lspManager() {
        return self.lspManager;
      },
      hasActiveLSP: () => self.hasActiveLSP(),
      analyze: () => self.analyze(),
      emit: (event: CodebaseContextEvent) => self.emit(event),
    };
  }
}

// =============================================================================
// FACTORY FUNCTIONS
// =============================================================================

/**
 * Create a codebase context manager.
 *
 * @example
 * ```typescript
 * const codebase = createCodebaseContext({
 *   root: './my-project',
 *   includePatterns: ['src/**\/*.ts'],
 *   excludePatterns: ['node_modules/**'],
 * });
 *
 * // Analyze repo
 * await codebase.analyze();
 *
 * // Select code for task
 * const selection = await codebase.selectRelevantCode({
 *   task: 'fix authentication bug',
 *   maxTokens: 10000,
 *   strategy: 'relevance_first',
 * });
 *
 * console.log(`Selected ${selection.chunks.length} files`);
 * console.log(`Using ${selection.totalTokens} tokens`);
 * ```
 */
export function createCodebaseContext(config: CodebaseContextConfig = {}): CodebaseContextManager {
  return new CodebaseContextManager(config);
}

/**
 * Minimal chunk interface for building context.
 * Only requires the properties actually used by buildContextFromChunks.
 */
export interface MinimalCodeChunk {
  filePath: string;
  content: string;
  tokenCount: number;
}

/**
 * Build context string from selected chunks.
 */
export function buildContextFromChunks(
  chunks: MinimalCodeChunk[],
  options: {
    includeFilePaths?: boolean;
    includeSeparators?: boolean;
    maxTotalTokens?: number;
  } = {},
): string {
  const { includeFilePaths = true, includeSeparators = true, maxTotalTokens } = options;

  const parts: string[] = [];
  let totalTokens = 0;

  for (const chunk of chunks) {
    if (maxTotalTokens && totalTokens + chunk.tokenCount > maxTotalTokens) {
      break;
    }

    if (includeSeparators && parts.length > 0) {
      parts.push('\n---\n');
    }

    if (includeFilePaths) {
      parts.push(`// File: ${chunk.filePath}\n`);
    }

    parts.push(chunk.content);
    totalTokens += chunk.tokenCount;
  }

  return parts.join('');
}

/**
 * Create a summary of the repo structure.
 */
export function summarizeRepoStructure(repoMap: RepoMap): string {
  const lines: string[] = [
    `Repository: ${repoMap.root}`,
    `Total files: ${repoMap.chunks.size}`,
    `Total tokens: ${repoMap.totalTokens.toLocaleString()}`,
    ``,
    `Entry points:`,
  ];

  for (const ep of repoMap.entryPoints.slice(0, 5)) {
    lines.push(`  - ${ep}`);
  }

  lines.push(``, `Core modules:`);
  for (const mod of repoMap.coreModules.slice(0, 5)) {
    lines.push(`  - ${mod}`);
  }

  // Type breakdown
  const byType = new Map<CodeChunkType, number>();
  for (const chunk of repoMap.chunks.values()) {
    byType.set(chunk.type, (byType.get(chunk.type) ?? 0) + 1);
  }

  lines.push(``, `File types:`);
  for (const [type, count] of byType) {
    lines.push(`  - ${type}: ${count}`);
  }

  return lines.join('\n');
}

/**
 * Generate an aider-style lightweight repo map: file tree with key symbols.
 * Used as fallback when task-specific selection returns nothing.
 */
export function generateLightweightRepoMap(repoMap: RepoMap, maxTokens: number = 10000): string {
  const lines: string[] = ['## Repository Map\n'];
  const byDir = new Map<string, CodeChunk[]>();
  for (const chunk of repoMap.chunks.values()) {
    const dir = path.dirname(chunk.filePath);
    if (!byDir.has(dir)) byDir.set(dir, []);
    byDir.get(dir)!.push(chunk);
  }

  let tokenEstimate = 0;
  for (const [dir, chunks] of [...byDir].sort((a, b) => a[0].localeCompare(b[0]))) {
    const dirLine = `${dir}/`;
    lines.push(dirLine);
    tokenEstimate += dirLine.length * 0.25;

    for (const chunk of chunks.sort((a, b) => b.importance - a.importance)) {
      const symbols = chunk.symbols.slice(0, 5).join(', ');
      const fileLine = `  ${path.basename(chunk.filePath)}${symbols ? ` (${symbols})` : ''}`;
      lines.push(fileLine);
      tokenEstimate += fileLine.length * 0.25;
      if (tokenEstimate > maxTokens) break;
    }
    if (tokenEstimate > maxTokens) {
      lines.push('  ... (truncated)');
      break;
    }
  }
  return lines.join('\n');
}
