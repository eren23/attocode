/**
 * Lesson 25: Rules System Integration
 *
 * Loads and applies rules from CLAUDE.md and other sources (from Lesson 12).
 * Rules can modify the system prompt, add constraints, or provide context.
 */

import { readFile } from 'node:fs/promises';
import { existsSync, watch, FSWatcher } from 'node:fs';
import { join, dirname, resolve } from 'node:path';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Rule source configuration.
 */
export interface RuleSource {
  type: 'file' | 'inline';
  path?: string;
  content?: string;
  priority?: number;
}

/**
 * Rules configuration.
 */
export interface RulesConfig {
  enabled?: boolean;
  sources?: RuleSource[];
  watch?: boolean;
}

/**
 * Loaded rule.
 */
export interface LoadedRule {
  source: string;
  content: string;
  priority: number;
  loadedAt: Date;
}

/**
 * Rules manager events.
 */
export type RulesEvent =
  | { type: 'rules.loaded'; count: number; sources: string[] }
  | { type: 'rules.reloaded'; source: string }
  | { type: 'rules.error'; source: string; error: string };

export type RulesEventListener = (event: RulesEvent) => void;

// =============================================================================
// RULES MANAGER
// =============================================================================

/**
 * RulesManager loads and manages rules from various sources.
 */
export class RulesManager {
  private config: RulesConfig;
  private rules: LoadedRule[] = [];
  private listeners: RulesEventListener[] = [];
  private watchers: FSWatcher[] = [];
  private baseDir: string;

  constructor(config: Partial<RulesConfig> = {}, baseDir?: string) {
    this.config = {
      enabled: config.enabled ?? true,
      sources: config.sources ?? [],
      watch: config.watch ?? false,
    };
    this.baseDir = baseDir || process.cwd();
  }

  /**
   * Load rules from configured sources.
   */
  async loadRules(): Promise<void> {
    if (!this.config.enabled) return;

    this.rules = [];
    const loadedSources: string[] = [];

    for (const source of this.config.sources || []) {
      try {
        const rule = await this.loadSource(source);
        if (rule) {
          this.rules.push(rule);
          loadedSources.push(rule.source);
        }
      } catch (err) {
        const error = err instanceof Error ? err.message : String(err);
        this.emit({ type: 'rules.error', source: source.path || 'inline', error });
      }
    }

    // Sort by priority (higher first)
    this.rules.sort((a, b) => b.priority - a.priority);

    this.emit({ type: 'rules.loaded', count: this.rules.length, sources: loadedSources });

    // Setup watchers if configured
    if (this.config.watch) {
      this.setupWatchers();
    }
  }

  /**
   * Load a single rule source.
   */
  private async loadSource(source: RuleSource): Promise<LoadedRule | null> {
    if (source.type === 'inline' && source.content) {
      return {
        source: 'inline',
        content: source.content,
        priority: source.priority ?? 0,
        loadedAt: new Date(),
      };
    }

    if (source.type === 'file' && source.path) {
      const resolvedPath = resolve(this.baseDir, source.path);

      if (!existsSync(resolvedPath)) {
        // File doesn't exist - not an error, just skip
        return null;
      }

      const content = await readFile(resolvedPath, 'utf-8');
      return {
        source: resolvedPath,
        content: content.trim(),
        priority: source.priority ?? 0,
        loadedAt: new Date(),
      };
    }

    return null;
  }

  /**
   * Setup file watchers for auto-reload.
   */
  private setupWatchers(): void {
    // Clean up existing watchers
    this.cleanupWatchers();

    for (const source of this.config.sources || []) {
      if (source.type === 'file' && source.path) {
        const resolvedPath = resolve(this.baseDir, source.path);

        if (existsSync(resolvedPath)) {
          try {
            const watcher = watch(resolvedPath, async (eventType) => {
              if (eventType === 'change') {
                await this.reloadSource(source);
              }
            });
            this.watchers.push(watcher);
          } catch {
            // Ignore watch errors (e.g., file system doesn't support watching)
          }
        }
      }
    }
  }

  /**
   * Reload a specific source.
   */
  private async reloadSource(source: RuleSource): Promise<void> {
    try {
      const rule = await this.loadSource(source);
      if (rule) {
        // Find and replace existing rule from this source
        const existingIndex = this.rules.findIndex(r => r.source === rule.source);
        if (existingIndex >= 0) {
          this.rules[existingIndex] = rule;
        } else {
          this.rules.push(rule);
          this.rules.sort((a, b) => b.priority - a.priority);
        }
        this.emit({ type: 'rules.reloaded', source: rule.source });
      }
    } catch (err) {
      const error = err instanceof Error ? err.message : String(err);
      this.emit({ type: 'rules.error', source: source.path || 'inline', error });
    }
  }

  /**
   * Clean up watchers.
   */
  private cleanupWatchers(): void {
    for (const watcher of this.watchers) {
      watcher.close();
    }
    this.watchers = [];
  }

  /**
   * Get all rules as a combined string for system prompt.
   */
  getRulesContent(): string {
    if (this.rules.length === 0) return '';

    return this.rules
      .map(r => `# Rules from ${r.source}\n\n${r.content}`)
      .join('\n\n---\n\n');
  }

  /**
   * Get rules as context strings for memory augmentation.
   */
  getRulesContext(): string[] {
    return this.rules.map(r => r.content);
  }

  /**
   * Get loaded rules.
   */
  getLoadedRules(): LoadedRule[] {
    return [...this.rules];
  }

  /**
   * Add a rule at runtime.
   */
  addRule(content: string, priority: number = 0, source: string = 'runtime'): void {
    this.rules.push({
      source,
      content,
      priority,
      loadedAt: new Date(),
    });
    this.rules.sort((a, b) => b.priority - a.priority);
  }

  /**
   * Remove a rule by source.
   */
  removeRule(source: string): boolean {
    const index = this.rules.findIndex(r => r.source === source);
    if (index >= 0) {
      this.rules.splice(index, 1);
      return true;
    }
    return false;
  }

  /**
   * Subscribe to events.
   */
  on(listener: RulesEventListener): () => void {
    this.listeners.push(listener);
    return () => {
      const idx = this.listeners.indexOf(listener);
      if (idx >= 0) this.listeners.splice(idx, 1);
    };
  }

  /**
   * Emit an event.
   */
  private emit(event: RulesEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch {
        // Ignore listener errors
      }
    }
  }

  /**
   * Cleanup resources.
   */
  cleanup(): void {
    this.cleanupWatchers();
    this.listeners = [];
    this.rules = [];
  }
}

// =============================================================================
// FACTORY
// =============================================================================

/**
 * Create a rules manager and load rules.
 */
export async function createRulesManager(
  config?: Partial<RulesConfig>,
  baseDir?: string
): Promise<RulesManager> {
  const manager = new RulesManager(config, baseDir);
  await manager.loadRules();
  return manager;
}

// =============================================================================
// DEFAULT SOURCES
// =============================================================================

/**
 * Default rule sources to check.
 */
export const DEFAULT_RULE_SOURCES: RuleSource[] = [
  // Project-level rules (highest priority)
  { type: 'file', path: '.agent/rules.md', priority: 10 },
  // Global CLAUDE.md at project root
  { type: 'file', path: 'CLAUDE.md', priority: 5 },
  // Alternative locations
  { type: 'file', path: '.agent/CLAUDE.md', priority: 5 },
  { type: 'file', path: 'docs/CLAUDE.md', priority: 3 },
];

/**
 * Parse rules from markdown content.
 * Extracts sections and returns structured rules.
 */
export function parseRulesFromMarkdown(content: string): {
  sections: Array<{ heading: string; content: string }>;
  raw: string;
} {
  const sections: Array<{ heading: string; content: string }> = [];
  const lines = content.split('\n');

  let currentHeading = '';
  let currentContent: string[] = [];

  for (const line of lines) {
    const headingMatch = line.match(/^(#{1,3})\s+(.+)$/);
    if (headingMatch) {
      // Save previous section
      if (currentHeading || currentContent.length > 0) {
        sections.push({
          heading: currentHeading,
          content: currentContent.join('\n').trim(),
        });
      }
      currentHeading = headingMatch[2];
      currentContent = [];
    } else {
      currentContent.push(line);
    }
  }

  // Save last section
  if (currentHeading || currentContent.length > 0) {
    sections.push({
      heading: currentHeading,
      content: currentContent.join('\n').trim(),
    });
  }

  return { sections, raw: content };
}
