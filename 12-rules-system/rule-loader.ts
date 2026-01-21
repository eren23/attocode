/**
 * Lesson 12: Rule Loader
 *
 * Discovers and loads instruction files from various sources.
 * Supports file system, URLs, and inline content.
 *
 * Key features:
 * - Automatic discovery of instruction files
 * - Caching for performance
 * - Error handling with graceful degradation
 */

import * as fs from 'fs/promises';
import * as path from 'path';
import type {
  InstructionSource,
  InstructionFile,
  InstructionFileSection,
  InstructionFileFrontmatter,
  RuleLoaderConfig,
  LoadResult,
  RuleType,
  Scope,
  DEFAULT_FILE_PATTERNS,
  SCOPE_PRIORITIES,
} from './types.js';

// =============================================================================
// DEFAULT CONFIGURATION
// =============================================================================

const DEFAULT_CONFIG: RuleLoaderConfig = {
  baseDir: process.cwd(),
  filePatterns: [
    'CLAUDE.md',
    'CLAUDE.local.md',
    'AGENTS.md',
    '.claude/CLAUDE.md',
    '.cursorrules',
  ],
  recursive: true,
  maxDepth: 5,
  timeout: 5000,
  cacheEnabled: true,
  cacheTTL: 60000, // 1 minute
};

// =============================================================================
// RULE LOADER
// =============================================================================

/**
 * Loader for instruction sources.
 */
export class RuleLoader {
  private config: RuleLoaderConfig;
  private cache: Map<string, { content: string; loadedAt: Date }> = new Map();

  constructor(config: Partial<RuleLoaderConfig> = {}) {
    this.config = { ...DEFAULT_CONFIG, ...config };
  }

  // =============================================================================
  // DISCOVERY
  // =============================================================================

  /**
   * Discover all instruction sources in the configured directories.
   */
  async discover(): Promise<InstructionSource[]> {
    const sources: InstructionSource[] = [];
    const visited = new Set<string>();

    // Search from base directory up to find project root markers
    let currentDir = this.config.baseDir;

    for (let depth = 0; depth < this.config.maxDepth; depth++) {
      // Check for instruction files in current directory
      for (const pattern of this.config.filePatterns) {
        const filePath = path.join(currentDir, pattern);

        if (visited.has(filePath)) continue;
        visited.add(filePath);

        try {
          await fs.access(filePath);

          const scope = this.inferScope(filePath);
          const priority = this.inferPriority(filePath, scope);

          sources.push({
            id: `file:${filePath}`,
            type: 'file',
            location: filePath,
            scope,
            priority,
            label: path.basename(filePath),
            enabled: true,
          });
        } catch {
          // File doesn't exist, skip
        }
      }

      // Check for git root or package.json to stop searching
      const hasProjectMarker = await this.hasProjectMarker(currentDir);
      if (hasProjectMarker && depth > 0) {
        break;
      }

      // Move up one directory
      const parentDir = path.dirname(currentDir);
      if (parentDir === currentDir) break;
      currentDir = parentDir;
    }

    // Also check user's home directory for global config
    const homeDir = process.env.HOME ?? process.env.USERPROFILE;
    if (homeDir) {
      const globalPaths = [
        path.join(homeDir, '.claude', 'CLAUDE.md'),
        path.join(homeDir, '.config', 'claude', 'CLAUDE.md'),
      ];

      for (const globalPath of globalPaths) {
        if (visited.has(globalPath)) continue;
        visited.add(globalPath);

        try {
          await fs.access(globalPath);
          sources.push({
            id: `file:${globalPath}`,
            type: 'file',
            location: globalPath,
            scope: 'global',
            priority: 100,
            label: 'Global config',
            enabled: true,
          });
        } catch {
          // File doesn't exist
        }
      }
    }

    // Sort by scope priority then by priority within scope
    return sources.sort((a, b) => {
      const scopeOrder: Record<Scope, number> = {
        global: 0,
        user: 1,
        project: 2,
        directory: 3,
        session: 4,
      };
      const scopeDiff = scopeOrder[a.scope] - scopeOrder[b.scope];
      if (scopeDiff !== 0) return scopeDiff;
      return a.priority - b.priority;
    });
  }

  /**
   * Check if directory has project markers (git, package.json, etc.).
   */
  private async hasProjectMarker(dir: string): Promise<boolean> {
    const markers = ['.git', 'package.json', 'Cargo.toml', 'pyproject.toml', 'go.mod'];

    for (const marker of markers) {
      try {
        await fs.access(path.join(dir, marker));
        return true;
      } catch {
        // Continue checking
      }
    }

    return false;
  }

  /**
   * Infer scope from file path.
   */
  private inferScope(filePath: string): Scope {
    const homeDir = process.env.HOME ?? process.env.USERPROFILE ?? '';

    // Global if in home directory config folders
    if (
      filePath.startsWith(path.join(homeDir, '.claude')) ||
      filePath.startsWith(path.join(homeDir, '.config'))
    ) {
      return 'global';
    }

    // User if in home directory
    if (filePath.startsWith(homeDir)) {
      return 'user';
    }

    // Directory if in subdirectory with local marker
    if (filePath.includes('.local.md') || path.basename(path.dirname(filePath)) !== this.config.baseDir) {
      return 'directory';
    }

    // Default to project
    return 'project';
  }

  /**
   * Infer priority from file path and scope.
   */
  private inferPriority(filePath: string, scope: Scope): number {
    const basePriority: Record<Scope, number> = {
      global: 500,
      user: 400,
      project: 300,
      directory: 200,
      session: 100,
    };

    let priority = basePriority[scope];

    // Local files have higher priority within their scope
    if (filePath.includes('.local.md')) {
      priority -= 50;
    }

    // AGENTS.md has slightly lower priority than CLAUDE.md
    if (path.basename(filePath) === 'AGENTS.md') {
      priority += 10;
    }

    return priority;
  }

  // =============================================================================
  // LOADING
  // =============================================================================

  /**
   * Load content from an instruction source.
   */
  async load(source: InstructionSource): Promise<LoadResult> {
    const startTime = performance.now();

    // Check cache
    if (this.config.cacheEnabled) {
      const cached = this.cache.get(source.id);
      if (cached && Date.now() - cached.loadedAt.getTime() < this.config.cacheTTL) {
        return {
          success: true,
          content: cached.content,
          cached: true,
          loadTimeMs: performance.now() - startTime,
        };
      }
    }

    try {
      let content: string;

      switch (source.type) {
        case 'file':
          content = await this.loadFile(source.location);
          break;

        case 'url':
          content = await this.loadUrl(source.location);
          break;

        case 'inline':
          content = source.location;
          break;

        case 'env':
          content = process.env[source.location] ?? '';
          break;

        default:
          throw new Error(`Unknown source type: ${source.type}`);
      }

      // Cache the result
      if (this.config.cacheEnabled) {
        this.cache.set(source.id, { content, loadedAt: new Date() });
      }

      return {
        success: true,
        content,
        cached: false,
        loadTimeMs: performance.now() - startTime,
      };
    } catch (err) {
      return {
        success: false,
        error: err instanceof Error ? err : new Error(String(err)),
        cached: false,
        loadTimeMs: performance.now() - startTime,
      };
    }
  }

  /**
   * Load content from a file.
   */
  private async loadFile(filePath: string): Promise<string> {
    return fs.readFile(filePath, 'utf-8');
  }

  /**
   * Load content from a URL.
   */
  private async loadUrl(url: string): Promise<string> {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), this.config.timeout);

    try {
      const response = await fetch(url, { signal: controller.signal });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      return response.text();
    } finally {
      clearTimeout(timeoutId);
    }
  }

  // =============================================================================
  // PARSING
  // =============================================================================

  /**
   * Parse an instruction file into structured format.
   */
  parseFile(content: string, filePath: string): InstructionFile {
    const lines = content.split('\n');
    let frontmatter: InstructionFileFrontmatter | undefined;
    let bodyStartIndex = 0;

    // Check for YAML frontmatter
    if (lines[0]?.trim() === '---') {
      const endIndex = lines.findIndex((line, i) => i > 0 && line.trim() === '---');

      if (endIndex > 0) {
        const frontmatterContent = lines.slice(1, endIndex).join('\n');
        frontmatter = this.parseFrontmatter(frontmatterContent);
        bodyStartIndex = endIndex + 1;
      }
    }

    // Parse body into sections
    const body = lines.slice(bodyStartIndex).join('\n');
    const sections = this.parseSections(body);

    return {
      path: filePath,
      frontmatter,
      sections,
      rawContent: content,
    };
  }

  /**
   * Parse YAML frontmatter.
   */
  private parseFrontmatter(content: string): InstructionFileFrontmatter {
    const frontmatter: InstructionFileFrontmatter = {};
    const lines = content.split('\n');

    for (const line of lines) {
      const match = line.match(/^(\w+):\s*(.+)$/);
      if (match) {
        const [, key, value] = match;

        switch (key) {
          case 'scope':
            if (['global', 'user', 'project', 'directory', 'session'].includes(value)) {
              frontmatter.scope = value as Scope;
            }
            break;

          case 'priority':
            frontmatter.priority = parseInt(value, 10);
            break;

          case 'enabled':
            frontmatter.enabled = value.toLowerCase() === 'true';
            break;

          case 'tags':
            frontmatter.tags = value.split(',').map((t) => t.trim());
            break;
        }
      }
    }

    return frontmatter;
  }

  /**
   * Parse content into sections based on markdown headings.
   */
  private parseSections(content: string): InstructionFileSection[] {
    const sections: InstructionFileSection[] = [];
    const lines = content.split('\n');

    let currentSection: InstructionFileSection = {
      content: '',
      ruleType: 'instruction',
    };

    for (const line of lines) {
      // Check for heading
      const headingMatch = line.match(/^(#{1,6})\s+(.+)$/);

      if (headingMatch) {
        // Save previous section if it has content
        if (currentSection.content.trim()) {
          sections.push(currentSection);
        }

        const level = headingMatch[1].length;
        const heading = headingMatch[2].trim();

        currentSection = {
          heading,
          level,
          content: '',
          ruleType: this.inferRuleType(heading),
        };
      } else {
        currentSection.content += line + '\n';
      }
    }

    // Save last section
    if (currentSection.content.trim()) {
      sections.push(currentSection);
    }

    return sections;
  }

  /**
   * Infer rule type from section heading.
   */
  private inferRuleType(heading: string): RuleType {
    const lower = heading.toLowerCase();

    if (lower.includes('constraint') || lower.includes('never') || lower.includes('don\'t')) {
      return 'constraint';
    }

    if (lower.includes('prefer') || lower.includes('should')) {
      return 'preference';
    }

    if (lower.includes('format') || lower.includes('output') || lower.includes('style')) {
      return 'format';
    }

    if (lower.includes('tool') || lower.includes('command')) {
      return 'tool-config';
    }

    if (lower.includes('persona') || lower.includes('role') || lower.includes('identity')) {
      return 'persona';
    }

    if (lower.includes('context') || lower.includes('background')) {
      return 'context';
    }

    return 'instruction';
  }

  // =============================================================================
  // CACHE MANAGEMENT
  // =============================================================================

  /**
   * Clear the cache.
   */
  clearCache(): void {
    this.cache.clear();
  }

  /**
   * Invalidate a specific cache entry.
   */
  invalidate(sourceId: string): boolean {
    return this.cache.delete(sourceId);
  }

  /**
   * Get cache statistics.
   */
  getCacheStats(): { size: number; entries: string[] } {
    return {
      size: this.cache.size,
      entries: [...this.cache.keys()],
    };
  }
}

// =============================================================================
// EXPORTS
// =============================================================================

export const defaultRuleLoader = new RuleLoader();
