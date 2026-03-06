/**
 * .agentignore Support
 *
 * AI-specific file exclusion patterns, separate from .gitignore.
 * Allows hiding files from the agent that shouldn't be modified or seen,
 * without affecting git behavior.
 *
 * Priority order (highest first):
 * 1. .agentignore in current directory
 * 2. .gitignore in current directory
 * 3. Global ~/.agent/ignore
 *
 * Usage:
 *   const ignore = createIgnoreManager();
 *   await ignore.load(process.cwd());
 *   const filtered = ignore.filterPaths(paths);
 */

import { readFile, stat } from 'fs/promises';
import { join, relative, isAbsolute, normalize, sep } from 'path';
import { homedir } from 'os';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Ignore pattern with metadata.
 */
export interface IgnorePattern {
  /** The pattern string */
  pattern: string;

  /** Whether this is a negation pattern (starts with !) */
  negated: boolean;

  /** Whether pattern is directory-only (ends with /) */
  directoryOnly: boolean;

  /** Compiled regex for matching */
  regex: RegExp;

  /** Source file */
  source: string;
}

/**
 * Ignore manager configuration.
 */
export interface IgnoreConfig {
  /** Enable/disable ignore functionality */
  enabled?: boolean;

  /** Whether to include .gitignore patterns */
  includeGitignore?: boolean;

  /** Whether to include global patterns */
  includeGlobal?: boolean;

  /** Additional patterns to include */
  extraPatterns?: string[];
}

/**
 * Ignore event types.
 */
export type IgnoreEvent =
  | { type: 'ignore.loaded'; source: string; patternCount: number }
  | { type: 'ignore.matched'; path: string; pattern: string }
  | { type: 'ignore.error'; source: string; error: string };

export type IgnoreEventListener = (event: IgnoreEvent) => void;

// =============================================================================
// GITIGNORE PATTERN COMPILER
// =============================================================================

/**
 * Convert a gitignore-style pattern to a regex.
 * Implements most of the gitignore specification.
 */
function compilePattern(pattern: string): RegExp {
  // Check if anchored to root (starts with /)
  const isAnchored = pattern.startsWith('/');

  // Remove leading and trailing slashes for processing
  let cleanPattern = pattern;
  if (isAnchored) {
    cleanPattern = cleanPattern.slice(1); // Remove leading /
  }
  if (cleanPattern.endsWith('/')) {
    cleanPattern = cleanPattern.slice(0, -1); // Remove trailing /
  }

  // Convert gitignore pattern to regex, processing glob patterns before escaping
  let regexStr = cleanPattern
    // First, replace ** with a placeholder
    .replace(/\*\*/g, '\x00GLOBSTAR\x00')
    // Then replace single *
    .replace(/\*/g, '\x00STAR\x00')
    // Then replace ?
    .replace(/\?/g, '\x00QUESTION\x00')
    // Escape remaining regex special chars
    .replace(/[.+^${}()|[\]\\]/g, '\\$&')
    // Restore glob patterns as regex
    .replace(/\x00GLOBSTAR\x00/g, '.*')
    .replace(/\x00STAR\x00/g, '[^/]*')
    .replace(/\x00QUESTION\x00/g, '[^/]');

  // Handle the prefix: **/ at start matches any depth including root
  if (cleanPattern.startsWith('**/')) {
    // The pattern can match at root level or at any subdirectory
    // (.*/)? matches optional path prefix, then the rest of the pattern
    regexStr = '(.*/)?' + regexStr.slice(4); // slice(4) removes the '.*/' from regex
  } else if (cleanPattern.startsWith('**')) {
    regexStr = `^${regexStr}`;
  } else if (!isAnchored) {
    // Match anywhere in path (at start or after /)
    regexStr = `(^|/)${regexStr}`;
  } else {
    // Anchored to root
    regexStr = `^${regexStr}`;
  }

  // Match at end of path or as a directory prefix
  regexStr = `${regexStr}(/.*)?$`;

  return new RegExp(regexStr);
}

/**
 * Parse a pattern line from ignore file.
 */
function parsePatternLine(line: string, source: string): IgnorePattern | null {
  // Trim whitespace
  let pattern = line.trim();

  // Skip empty lines and comments
  if (!pattern || pattern.startsWith('#')) {
    return null;
  }

  // Check for negation
  let negated = false;
  if (pattern.startsWith('!')) {
    negated = true;
    pattern = pattern.slice(1);
  }

  // Check for directory-only
  const directoryOnly = pattern.endsWith('/');

  // Compile to regex
  const regex = compilePattern(pattern);

  return {
    pattern,
    negated,
    directoryOnly,
    regex,
    source,
  };
}

// =============================================================================
// DEFAULT PATTERNS
// =============================================================================

/**
 * Built-in patterns that are always ignored.
 */
const BUILTIN_PATTERNS = [
  // Version control
  '.git',
  '.svn',
  '.hg',

  // Dependencies
  'node_modules',
  '__pycache__',
  '.venv',
  'venv',

  // IDE/Editor
  '.idea',
  '.vscode',
  '*.swp',
  '*.swo',
  '*~',

  // OS files
  '.DS_Store',
  'Thumbs.db',

  // Build outputs (common)
  'dist',
  'build',
  'out',

  // Sensitive files
  '.env',
  '.env.local',
  '*.pem',
  '*.key',
  'credentials.json',
  'secrets.json',
];

// =============================================================================
// IGNORE MANAGER
// =============================================================================

/**
 * Manages ignore patterns for file filtering.
 */
export class IgnoreManager {
  private config: Required<IgnoreConfig>;
  private patterns: IgnorePattern[] = [];
  private workspaceRoot: string = process.cwd();
  private eventListeners: Set<IgnoreEventListener> = new Set();
  private loaded: boolean = false;

  constructor(config: IgnoreConfig = {}) {
    this.config = {
      enabled: config.enabled ?? true,
      includeGitignore: config.includeGitignore ?? true,
      includeGlobal: config.includeGlobal ?? true,
      extraPatterns: config.extraPatterns ?? [],
    };

    // Add built-in patterns
    this.addPatterns(BUILTIN_PATTERNS, 'built-in');

    // Add extra patterns from config
    if (this.config.extraPatterns.length > 0) {
      this.addPatterns(this.config.extraPatterns, 'config');
    }
  }

  /**
   * Load ignore patterns from files.
   */
  async load(workspaceRoot?: string): Promise<void> {
    if (!this.config.enabled) return;

    this.workspaceRoot = workspaceRoot ?? process.cwd();

    // Load global patterns first (lowest priority)
    if (this.config.includeGlobal) {
      await this.loadFromFile(join(homedir(), '.agent', 'ignore'));
    }

    // Load .gitignore (medium priority)
    if (this.config.includeGitignore) {
      await this.loadFromFile(join(this.workspaceRoot, '.gitignore'));
    }

    // Load .agentignore (highest priority)
    await this.loadFromFile(join(this.workspaceRoot, '.agentignore'));

    this.loaded = true;
  }

  /**
   * Load patterns from a file.
   */
  private async loadFromFile(filePath: string): Promise<void> {
    try {
      const content = await readFile(filePath, 'utf-8');
      const lines = content.split('\n');
      let count = 0;

      for (const line of lines) {
        const pattern = parsePatternLine(line, filePath);
        if (pattern) {
          this.patterns.push(pattern);
          count++;
        }
      }

      this.emit({ type: 'ignore.loaded', source: filePath, patternCount: count });
    } catch {
      // File doesn't exist - that's ok
    }
  }

  /**
   * Add patterns programmatically.
   */
  addPatterns(patterns: string[], source: string = 'manual'): void {
    for (const line of patterns) {
      const pattern = parsePatternLine(line, source);
      if (pattern) {
        this.patterns.push(pattern);
      }
    }
  }

  /**
   * Check if a path should be ignored.
   */
  shouldIgnore(path: string, isDirectory: boolean = false): boolean {
    if (!this.config.enabled) return false;

    // Normalize the path
    let normalizedPath = this.normalizePath(path);

    // If path ends with /, treat it as a directory
    if (normalizedPath.endsWith('/')) {
      isDirectory = true;
      normalizedPath = normalizedPath.slice(0, -1);
    }

    let ignored = false;

    for (const pattern of this.patterns) {
      // Skip directory-only patterns for files
      if (pattern.directoryOnly && !isDirectory) {
        // However, if the path is inside a directory that matches,
        // we should still ignore it (e.g., temp/cache matches temp/)
        const dirPath = normalizedPath.split('/').slice(0, -1).join('/');
        if (dirPath && pattern.regex.test(dirPath)) {
          ignored = true;
          this.emit({ type: 'ignore.matched', path, pattern: pattern.pattern });
          continue;
        }
        continue;
      }

      const matches = pattern.regex.test(normalizedPath);

      if (matches) {
        if (pattern.negated) {
          // Negation pattern - unignore
          ignored = false;
        } else {
          // Regular pattern - ignore
          ignored = true;
          this.emit({ type: 'ignore.matched', path, pattern: pattern.pattern });
        }
      }
    }

    return ignored;
  }

  /**
   * Filter a list of paths, removing ignored ones.
   */
  filterPaths(paths: string[]): string[] {
    return paths.filter((path) => !this.shouldIgnore(path));
  }

  /**
   * Filter paths with directory info.
   */
  async filterPathsWithStats(paths: string[]): Promise<string[]> {
    const results: string[] = [];

    for (const path of paths) {
      try {
        const stats = await stat(path);
        if (!this.shouldIgnore(path, stats.isDirectory())) {
          results.push(path);
        }
      } catch {
        // File doesn't exist or can't be read - include it
        if (!this.shouldIgnore(path)) {
          results.push(path);
        }
      }
    }

    return results;
  }

  /**
   * Get all patterns for debugging.
   */
  getPatterns(): IgnorePattern[] {
    return [...this.patterns];
  }

  /**
   * Check if patterns have been loaded.
   */
  isLoaded(): boolean {
    return this.loaded;
  }

  /**
   * Clear all patterns.
   */
  clear(): void {
    this.patterns = [];
    this.loaded = false;
  }

  /**
   * Reload patterns from files.
   */
  async reload(): Promise<void> {
    this.patterns = [];
    this.addPatterns(BUILTIN_PATTERNS, 'built-in');
    this.addPatterns(this.config.extraPatterns, 'config');
    await this.load(this.workspaceRoot);
  }

  /**
   * Subscribe to events.
   */
  subscribe(listener: IgnoreEventListener): () => void {
    this.eventListeners.add(listener);
    return () => this.eventListeners.delete(listener);
  }

  /**
   * Cleanup resources.
   */
  cleanup(): void {
    this.patterns = [];
    this.eventListeners.clear();
    this.loaded = false;
  }

  // Internal methods

  /**
   * Normalize a path for matching.
   */
  private normalizePath(path: string): string {
    // Make path relative to workspace root
    let normalizedPath = path;

    if (isAbsolute(path)) {
      normalizedPath = relative(this.workspaceRoot, path);
    }

    // Normalize separators to /
    normalizedPath = normalize(normalizedPath).replace(new RegExp(`\\${sep}`, 'g'), '/');

    // Remove leading ./
    if (normalizedPath.startsWith('./')) {
      normalizedPath = normalizedPath.slice(2);
    }

    return normalizedPath;
  }

  private emit(event: IgnoreEvent): void {
    for (const listener of this.eventListeners) {
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
 * Create an ignore manager.
 */
export function createIgnoreManager(config?: IgnoreConfig): IgnoreManager {
  return new IgnoreManager(config);
}

/**
 * Quick check if a path should be ignored using default patterns.
 */
export function quickShouldIgnore(path: string): boolean {
  const manager = new IgnoreManager({ includeGitignore: false, includeGlobal: false });
  return manager.shouldIgnore(path);
}

/**
 * Get sample .agentignore content.
 */
export function getSampleAgentignore(): string {
  return `# .agentignore - AI-specific file exclusion
# Files listed here will be hidden from the AI agent
# but remain visible to git and other tools

# Large data files that don't need AI analysis
data/
*.csv
*.json.bak

# Generated documentation
docs/api/
docs/generated/

# Test fixtures with large data
tests/fixtures/large/

# Temporary development files
scratch/
notes.md

# Sensitive configuration not needed for code changes
.env.production
config/secrets/

# Build artifacts already in .gitignore but ensure agent ignores
coverage/
.nyc_output/

# IDE project files
*.code-workspace
.project
.classpath
`;
}

/**
 * Get built-in patterns for reference.
 */
export function getBuiltinIgnorePatterns(): string[] {
  return [...BUILTIN_PATTERNS];
}
