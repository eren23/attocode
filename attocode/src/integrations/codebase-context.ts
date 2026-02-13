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
 */

import * as fs from 'fs/promises';
import * as path from 'path';
import type { LSPManager, LSPLocation } from './lsp.js';

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
  /** Symbols imported/used by this chunk */
  dependencies: string[];
  /** Last modified timestamp */
  lastModified?: Date;
}

export type CodeChunkType =
  | 'entry_point'    // Main entry points (index.ts, main.ts, app.ts)
  | 'core_module'    // Core business logic
  | 'utility'        // Utility/helper functions
  | 'types'          // Type definitions
  | 'config'         // Configuration files
  | 'test'           // Test files
  | 'documentation'  // Markdown, comments
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
  | 'importance_first'    // Select by importance, then fit to budget
  | 'relevance_first'     // Select by task relevance, then fit
  | 'breadth_first'       // Select diverse files first
  | 'depth_first';        // Select related files deeply

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
    '**/index.ts', '**/index.tsx', '**/index.js',
    '**/main.ts', '**/main.py', '**/main.go',
    '**/app.ts', '**/app.tsx', '**/app.py',
    '**/server.ts', '**/server.js',
    '**/cli.ts', '**/cli.js',
  ],
  coreModulePatterns: [
    '**/src/**', '**/lib/**', '**/core/**',
    '**/services/**', '**/modules/**',
  ],
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

  constructor(config: CodebaseContextConfig = {}) {
    this.config = { ...DEFAULT_CONFIG, ...config };
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

      // Discover files
      const files = await this.discoverFiles(repoRoot);

      // Process each file
      for (const filePath of files) {
        const chunk = await this.processFile(repoRoot, filePath);
        if (chunk) {
          chunks.set(chunk.id, chunk);

          // Track entry points
          if (chunk.type === 'entry_point') {
            entryPoints.push(filePath);
          }

          // Build dependency graph
          if (this.config.analyzeDependencies) {
            const deps = this.extractDependencies(chunk.content, filePath);
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

      // Calculate total tokens
      let totalTokens = 0;
      for (const chunk of chunks.values()) {
        totalTokens += chunk.tokenCount;
      }

      // Adjust importance based on dependency graph
      this.adjustImportanceByConnectivity(chunks, reverseDependencyGraph);

      // Identify core modules
      const moduleDirs = new Set<string>();
      for (const filePath of files) {
        const dir = path.dirname(filePath);
        if (this.matchesPatterns(dir, this.config.coreModulePatterns)) {
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

      this.emit({
        type: 'analysis.completed',
        totalFiles: chunks.size,
        totalTokens,
      });

      return repoMap;
    } catch (error) {
      this.emit({ type: 'analysis.error', error: error as Error });
      throw error;
    }
  }

  /**
   * Discover files matching include patterns.
   */
  private async discoverFiles(root: string): Promise<string[]> {
    const files: string[] = [];

    const walk = async (dir: string): Promise<void> => {
      const entries = await fs.readdir(dir, { withFileTypes: true });

      for (const entry of entries) {
        const fullPath = path.join(dir, entry.name);
        const relativePath = path.relative(root, fullPath);

        // Check exclusions first
        if (this.matchesPatterns(relativePath, this.config.excludePatterns)) {
          continue;
        }

        if (entry.isDirectory()) {
          await walk(fullPath);
        } else if (entry.isFile()) {
          if (this.matchesPatterns(relativePath, this.config.includePatterns)) {
            files.push(relativePath);
          }
        }
      }
    };

    await walk(root);
    return files;
  }

  /**
   * Process a single file into a code chunk.
   */
  private async processFile(root: string, relativePath: string): Promise<CodeChunk | null> {
    const fullPath = path.join(root, relativePath);

    try {
      const stat = await fs.stat(fullPath);

      // Skip large files
      if (stat.size > this.config.maxFileSize) {
        return null;
      }

      const content = await fs.readFile(fullPath, 'utf-8');
      const tokenCount = Math.ceil(content.length * this.config.tokensPerChar);
      const type = this.determineChunkType(relativePath, content);
      const symbols = this.extractSymbols(content, relativePath);
      const dependencies = this.extractDependencyNames(content);

      // Calculate base importance
      const importance = this.calculateBaseImportance(type, relativePath);

      return {
        id: relativePath,
        filePath: relativePath,
        content,
        tokenCount,
        importance,
        type,
        symbols,
        dependencies,
        lastModified: stat.mtime,
      };
    } catch {
      return null;
    }
  }

  /**
   * Determine the type of a code chunk.
   */
  private determineChunkType(filePath: string, content: string): CodeChunkType {
    const lower = filePath.toLowerCase();

    // Entry points
    if (this.matchesPatterns(filePath, this.config.entryPointPatterns)) {
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
    if (this.matchesPatterns(filePath, this.config.coreModulePatterns)) {
      return 'core_module';
    }

    return 'other';
  }

  /**
   * Calculate base importance for a chunk type.
   */
  private calculateBaseImportance(type: CodeChunkType, filePath: string): number {
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
   * Extract exported symbols from code.
   */
  private extractSymbols(content: string, filePath: string): string[] {
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
   * Extract dependency file paths from imports.
   */
  private extractDependencies(content: string, currentFile: string): Set<string> {
    const deps = new Set<string>();
    const ext = path.extname(currentFile);
    const dir = path.dirname(currentFile);

    if (['.ts', '.tsx', '.js', '.jsx'].includes(ext)) {
      // Match import statements
      const importPattern = /import\s+.*?\s+from\s+['"]([^'"]+)['"]/g;
      let match;

      while ((match = importPattern.exec(content)) !== null) {
        const importPath = match[1];

        // Only track relative imports
        if (importPath.startsWith('.')) {
          const resolved = path.normalize(path.join(dir, importPath));

          // Add possible extensions
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
   */
  private extractDependencyNames(content: string): string[] {
    const deps: string[] = [];

    // Extract imported names
    const patterns = [
      /import\s+\{\s*([^}]+)\s*\}\s+from/g,
      /import\s+(\w+)\s+from/g,
    ];

    for (const pattern of patterns) {
      let match;
      while ((match = pattern.exec(content)) !== null) {
        const captured = match[1];
        if (captured.includes(',')) {
          deps.push(...captured.split(',').map((s) => s.trim().split(' ')[0]));
        } else {
          deps.push(captured);
        }
      }
    }

    return deps;
  }

  /**
   * Adjust importance based on how many files depend on each chunk.
   */
  private adjustImportanceByConnectivity(
    chunks: Map<string, CodeChunk>,
    reverseDeps: Map<string, Set<string>>
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

  /**
   * Check if a path matches any of the given patterns.
   */
  private matchesPatterns(filePath: string, patterns: string[]): boolean {
    for (const pattern of patterns) {
      if (this.matchesGlob(filePath, pattern)) {
        return true;
      }
    }
    return false;
  }

  /**
   * Simple glob matching (supports * and **).
   */
  private matchesGlob(filePath: string, pattern: string): boolean {
    // Convert glob to regex
    const regexStr = pattern
      .replace(/\*\*/g, '<<<DOUBLESTAR>>>')
      .replace(/\*/g, '[^/]*')
      .replace(/<<<DOUBLESTAR>>>/g, '.*')
      .replace(/\?/g, '.');

    const regex = new RegExp(`^${regexStr}$`);
    return regex.test(filePath);
  }

  // ===========================================================================
  // SELECTION
  // ===========================================================================

  /**
   * Select relevant code chunks for a task within a token budget.
   */
  async selectRelevantCode(options: SelectionOptions): Promise<SelectionResult> {
    // Ensure we have an analyzed repo
    if (!this.repoMap) {
      await this.analyze();
    }

    const repoMap = this.repoMap!;
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
        relevance: this.calculateRelevance(chunk, task),
      }));
    }

    // Sort based on strategy
    candidates = this.sortByStrategy(candidates, strategy, task);

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

    this.emit({
      type: 'selection.completed',
      selected: selected.length,
      budget: maxTokens,
    });

    return result;
  }

  // ===========================================================================
  // LSP-ENHANCED CONTEXT SELECTION
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
    const {
      editingFile,
      editingPosition,
      lspBoostFactor = 0.3,
      ...baseOptions
    } = options;

    // Start with base selection
    const baseResult = await this.selectRelevantCode(baseOptions);

    // If no LSP or no editing file, return base result
    if (!this.lspManager || !editingFile || !this.hasActiveLSP()) {
      return {
        ...baseResult,
        lspEnhancements: null,
        lspBoostedFiles: [],
      };
    }

    // Gather LSP enhancements
    const enhancements = await this.gatherLSPEnhancements(editingFile, editingPosition);

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
    const repoMap = this.repoMap!;
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
          relevance: this.calculateRelevance(chunk, baseOptions.task!),
        }))
      : candidates;

    // Sort and select within budget
    const sorted = this.sortByStrategy(
      withRelevance,
      baseOptions.strategy ?? 'importance_first',
      baseOptions.task
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
  private async gatherLSPEnhancements(
    file: string,
    position?: SourcePosition
  ): Promise<LSPEnhancements> {
    const enhancements: LSPEnhancements = {
      referencingFiles: [],
      referencedFiles: [],
    };

    if (!this.lspManager) return enhancements;

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
        const refs = await this.lspManager.getReferences(file, pos.line, pos.character, false);
        for (const ref of refs) {
          const refFile = this.uriToPath(ref.uri);
          if (refFile && refFile !== file && !seenRefs.has(refFile)) {
            seenRefs.add(refFile);
            enhancements.referencingFiles.push(refFile);
          }
        }
      }

      // Get definition to find what this file depends on
      if (position) {
        const def = await this.lspManager.getDefinition(file, position.line, position.character);
        if (def) {
          const defFile = this.uriToPath(def.uri);
          if (defFile && defFile !== file) {
            enhancements.referencedFiles.push(defFile);

            // Get symbol info from hover
            const hover = await this.lspManager.getHover(file, position.line, position.character);
            if (hover) {
              const symbolName = this.extractSymbolName(hover);
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
      if (this.repoMap) {
        const deps = this.repoMap.dependencyGraph.get(file);
        if (deps) {
          for (const dep of deps) {
            if (!enhancements.referencedFiles.includes(dep)) {
              enhancements.referencedFiles.push(dep);
            }
          }
        }

        const reverseDeps = this.repoMap.reverseDependencyGraph.get(file);
        if (reverseDeps) {
          for (const dep of reverseDeps) {
            if (!enhancements.referencingFiles.includes(dep)) {
              enhancements.referencingFiles.push(dep);
            }
          }
        }
      }
    } catch (error) {
      // LSP errors shouldn't break context selection
      // Just return what we have
    }

    return enhancements;
  }

  /**
   * Convert LSP URI to file path.
   */
  private uriToPath(uri: string): string | null {
    if (uri.startsWith('file://')) {
      return uri.slice(7);
    }
    return uri;
  }

  /**
   * Extract symbol name from hover text.
   */
  private extractSymbolName(hover: string): string | null {
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

  /**
   * Calculate task relevance for a chunk.
   */
  private calculateRelevance(chunk: CodeChunk, task: string): number {
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
  private sortByStrategy(
    candidates: (CodeChunk & { relevance?: number })[],
    strategy: SelectionStrategy,
    task?: string
  ): CodeChunk[] {
    switch (strategy) {
      case 'importance_first':
        return candidates.sort((a, b) => b.importance - a.importance);

      case 'relevance_first':
        if (!task) return this.sortByStrategy(candidates, 'importance_first');
        return candidates.sort((a, b) => {
          const relDiff = (b.relevance ?? 0) - (a.relevance ?? 0);
          if (Math.abs(relDiff) > 0.1) return relDiff;
          return b.importance - a.importance;
        });

      case 'breadth_first':
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

  // ===========================================================================
  // INCREMENTAL EXPANSION
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
    }
  ): Promise<CodeChunk[]> {
    if (!this.repoMap) {
      await this.analyze();
    }

    const repoMap = this.repoMap!;
    const currentIds = new Set(currentChunks.map((c) => c.id));
    const candidates: CodeChunk[] = [];

    for (const chunk of currentChunks) {
      // Get dependencies
      if (options.direction === 'dependencies' || options.direction === 'both') {
        const deps = repoMap.dependencyGraph.get(chunk.filePath);
        if (deps) {
          for (const dep of deps) {
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
      filtered = candidates.filter((c) => this.calculateRelevance(c, options.query!) > 0);
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
   * Clear cached data.
   */
  clearCache(): void {
    this.cache.clear();
    this.repoMap = null;
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
  // ENHANCED SEARCH (Phase 4.4)
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
    const {
      includeSymbols = true,
      includePaths = true,
      includeContent = false,
      caseSensitive = false,
      fuzzyMatch = false,
      maxDistance = 2,
    } = options;

    if (!this.repoMap) return [];

    const queryTerms = this.tokenizeQuery(query);
    if (queryTerms.length === 0) return [];

    const normalize = caseSensitive
      ? (s: string) => s
      : (s: string) => s.toLowerCase();

    const chunks = Array.from(this.repoMap.chunks.values());

    return chunks.filter(chunk => {
      // Symbol matching (most relevant for code search)
      if (includeSymbols && chunk.symbols.length > 0) {
        const symbolMatch = chunk.symbols.some(symbol => {
          const normalizedSymbol = normalize(symbol);
          return queryTerms.some(term => {
            if (fuzzyMatch) {
              return this.fuzzyMatch(normalizedSymbol, normalize(term), maxDistance);
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
          if (fuzzyMatch) {
            const filename = path.basename(chunk.filePath, path.extname(chunk.filePath));
            return this.fuzzyMatch(normalize(filename), normalizedTerm, maxDistance);
          }
          return false;
        });
        if (pathMatch) return true;
      }

      // Content matching (expensive, off by default)
      if (includeContent) {
        const normalizedContent = normalize(chunk.content);
        const contentMatch = queryTerms.every(term =>
          normalizedContent.includes(normalize(term))
        );
        if (contentMatch) return true;
      }

      return false;
    });
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
    const { limit, ...searchOptions } = options;

    const matches = this.search(query, searchOptions);

    const scored = matches.map(chunk => ({
      chunk,
      score: this.calculateSearchScore(chunk, query),
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
  private calculateSearchScore(chunk: CodeChunk, query: string): number {
    const queryLower = query.toLowerCase();
    const queryTerms = this.tokenizeQuery(query);
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

  /**
   * Tokenize a search query into terms.
   */
  private tokenizeQuery(query: string): string[] {
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
  private fuzzyMatch(a: string, b: string, maxDistance: number): boolean {
    // Quick length check
    if (Math.abs(a.length - b.length) > maxDistance) return false;

    // If one contains the other, it's a match
    if (a.includes(b) || b.includes(a)) return true;

    // Compute Levenshtein distance
    const distance = this.levenshteinDistance(a, b);
    return distance <= maxDistance;
  }

  /**
   * Compute Levenshtein distance between two strings.
   */
  private levenshteinDistance(a: string, b: string): number {
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
export function createCodebaseContext(
  config: CodebaseContextConfig = {}
): CodebaseContextManager {
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
  } = {}
): string {
  const {
    includeFilePaths = true,
    includeSeparators = true,
    maxTotalTokens,
  } = options;

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
