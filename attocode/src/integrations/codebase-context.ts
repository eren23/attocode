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

  constructor(config: CodebaseContextConfig = {}) {
    this.config = { ...DEFAULT_CONFIG, ...config };
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
 * Build context string from selected chunks.
 */
export function buildContextFromChunks(
  chunks: CodeChunk[],
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
