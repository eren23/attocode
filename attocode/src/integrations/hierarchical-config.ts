/**
 * Hierarchical Configuration Integration
 *
 * Manages configuration that cascades from global to local levels:
 * - Default (built-in defaults from defaults.ts)
 * - Global (~/.agent/config.json)
 * - Workspace (.agent/config.json)
 * - Session (runtime overrides)
 *
 * Higher priority levels override lower ones.
 * Inspired by VS Code settings hierarchy and adapted from 24-advanced-patterns/hierarchical-state.ts.
 */

import * as fs from 'fs';
import * as path from 'path';
import { homedir } from 'os';

// =============================================================================
// TYPES
// =============================================================================

/**
 * Configuration levels in priority order (lowest to highest).
 */
export type ConfigLevel = 'default' | 'global' | 'workspace' | 'session' | 'override';

/**
 * Configuration at a specific level.
 */
export interface LevelConfig {
  level: ConfigLevel;
  values: Record<string, unknown>;
  source?: string;
  loadedAt: Date;
}

/**
 * Resolved configuration with source tracking.
 */
export interface ResolvedConfig<T = Record<string, unknown>> {
  config: T;
  sources: Record<string, ConfigLevel>;
  levels: ConfigLevel[];
  resolvedAt: Date;
}

/**
 * Configuration event types.
 */
export type ConfigEvent =
  | { type: 'config.loaded'; level: ConfigLevel; source: string }
  | { type: 'config.changed'; key: string; oldValue: unknown; newValue: unknown; level: ConfigLevel }
  | { type: 'config.resolved'; config: ResolvedConfig }
  | { type: 'config.error'; level: ConfigLevel; error: string };

export type ConfigEventListener = (event: ConfigEvent) => void;

/**
 * Hierarchical config manager options.
 */
export interface HierarchicalConfigOptions {
  /** Base directory for workspace config (defaults to cwd) */
  workspaceDir?: string;
  /** Path to global config (defaults to ~/.agent/config.json) */
  globalConfigPath?: string;
  /** Filename for workspace config (defaults to .agent/config.json) */
  workspaceConfigFile?: string;
  /** Auto-load global and workspace configs on creation */
  autoLoad?: boolean;
  /** Watch for file changes */
  watch?: boolean;
}

// =============================================================================
// HIERARCHICAL CONFIG MANAGER
// =============================================================================

/**
 * Manages hierarchical configuration for the agent.
 */
export class HierarchicalConfigManager<T extends Record<string, unknown> = Record<string, unknown>> {
  private levels: Map<ConfigLevel, LevelConfig> = new Map();
  private eventListeners: Set<ConfigEventListener> = new Set();
  private resolvedCache: ResolvedConfig<T> | null = null;
  private options: Required<HierarchicalConfigOptions>;
  private watchers: fs.FSWatcher[] = [];

  // Priority order (higher index = higher priority)
  private static readonly PRIORITY: ConfigLevel[] = [
    'default',
    'global',
    'workspace',
    'session',
    'override',
  ];

  constructor(defaults?: Partial<T>, options: HierarchicalConfigOptions = {}) {
    this.options = {
      workspaceDir: options.workspaceDir ?? process.cwd(),
      globalConfigPath: options.globalConfigPath ?? path.join(homedir(), '.agent', 'config.json'),
      workspaceConfigFile: options.workspaceConfigFile ?? '.agent/config.json',
      autoLoad: options.autoLoad ?? true,
      watch: options.watch ?? false,
    };

    // Set up default level
    if (defaults) {
      this.setLevel('default', defaults as Record<string, unknown>, 'built-in');
    }

    // Auto-load if enabled
    if (this.options.autoLoad) {
      this.loadAll();
    }
  }

  // ===========================================================================
  // LEVEL MANAGEMENT
  // ===========================================================================

  /**
   * Set configuration at a specific level.
   */
  setLevel(level: ConfigLevel, values: Record<string, unknown>, source?: string): void {
    const config: LevelConfig = {
      level,
      values,
      source,
      loadedAt: new Date(),
    };

    const oldConfig = this.levels.get(level);
    this.levels.set(level, config);
    this.resolvedCache = null;

    this.emit({ type: 'config.loaded', level, source: source || 'unknown' });

    // Emit change events for affected keys
    if (oldConfig) {
      for (const key of Object.keys(values)) {
        if (values[key] !== oldConfig.values[key]) {
          this.emit({
            type: 'config.changed',
            key,
            oldValue: oldConfig.values[key],
            newValue: values[key],
            level,
          });
        }
      }
    }
  }

  /**
   * Get configuration at a specific level.
   */
  getLevel(level: ConfigLevel): LevelConfig | undefined {
    return this.levels.get(level);
  }

  /**
   * Update specific keys at a level.
   */
  updateLevel(level: ConfigLevel, updates: Partial<Record<string, unknown>>): void {
    const existing = this.levels.get(level);
    const values = existing ? { ...existing.values, ...updates } : updates;
    this.setLevel(level, values, existing?.source);
  }

  // ===========================================================================
  // SESSION OVERRIDES
  // ===========================================================================

  /**
   * Set a session override (highest priority besides explicit override).
   */
  setSessionOverride<K extends keyof T>(key: K, value: T[K]): void {
    const session = this.levels.get('session') || {
      level: 'session' as ConfigLevel,
      values: {},
      loadedAt: new Date(),
    };

    const oldValue = session.values[key as string];
    session.values[key as string] = value;
    this.levels.set('session', session);
    this.resolvedCache = null;

    if (oldValue !== value) {
      this.emit({
        type: 'config.changed',
        key: key as string,
        oldValue,
        newValue: value,
        level: 'session',
      });
    }
  }

  /**
   * Clear a session override.
   */
  clearSessionOverride(key: keyof T): void {
    const session = this.levels.get('session');
    if (session && key in session.values) {
      const oldValue = session.values[key as string];
      delete session.values[key as string];
      this.resolvedCache = null;
      this.emit({
        type: 'config.changed',
        key: key as string,
        oldValue,
        newValue: undefined,
        level: 'session',
      });
    }
  }

  /**
   * Clear all session overrides.
   */
  clearSessionOverrides(): void {
    this.levels.delete('session');
    this.resolvedCache = null;
  }

  // ===========================================================================
  // RESOLUTION
  // ===========================================================================

  /**
   * Resolve the complete configuration by merging all levels.
   */
  resolve(): ResolvedConfig<T> {
    if (this.resolvedCache) {
      return this.resolvedCache;
    }

    const config: Record<string, unknown> = {};
    const sources: Record<string, ConfigLevel> = {};
    const contributingLevels: Set<ConfigLevel> = new Set();

    // Merge in priority order (lowest to highest)
    for (const level of HierarchicalConfigManager.PRIORITY) {
      const levelConfig = this.levels.get(level);
      if (!levelConfig) continue;

      contributingLevels.add(level);

      for (const [key, value] of Object.entries(levelConfig.values)) {
        if (value !== undefined) {
          config[key] = value;
          sources[key] = level;
        }
      }
    }

    const resolved: ResolvedConfig<T> = {
      config: config as T,
      sources,
      levels: Array.from(contributingLevels),
      resolvedAt: new Date(),
    };

    this.resolvedCache = resolved;
    this.emit({ type: 'config.resolved', config: resolved });

    return resolved;
  }

  /**
   * Get a specific configuration value.
   */
  get<K extends keyof T>(key: K): T[K] | undefined {
    const resolved = this.resolve();
    return resolved.config[key];
  }

  /**
   * Get a value with a default fallback.
   */
  getWithDefault<K extends keyof T>(key: K, defaultValue: T[K]): T[K] {
    const value = this.get(key);
    return value !== undefined ? value : defaultValue;
  }

  /**
   * Get which level a value came from.
   */
  getSource(key: keyof T): ConfigLevel | undefined {
    const resolved = this.resolve();
    return resolved.sources[key as string];
  }

  /**
   * Get the resolved config object.
   */
  getConfig(): T {
    return this.resolve().config;
  }

  // ===========================================================================
  // FILE LOADING
  // ===========================================================================

  /**
   * Load global configuration from file.
   */
  loadGlobal(): boolean {
    return this.loadFromFile(this.options.globalConfigPath, 'global');
  }

  /**
   * Load workspace configuration from file.
   */
  loadWorkspace(): boolean {
    const configPath = path.join(this.options.workspaceDir, this.options.workspaceConfigFile);
    return this.loadFromFile(configPath, 'workspace');
  }

  /**
   * Load configuration from a file.
   */
  loadFromFile(filePath: string, level: ConfigLevel): boolean {
    try {
      if (!fs.existsSync(filePath)) {
        return false;
      }

      const content = fs.readFileSync(filePath, 'utf-8');
      const values = JSON.parse(content);

      this.setLevel(level, values, filePath);

      // Set up watching if enabled
      if (this.options.watch) {
        this.watchFile(filePath, level);
      }

      return true;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.emit({ type: 'config.error', level, error: `Failed to load ${filePath}: ${message}` });
      return false;
    }
  }

  /**
   * Watch a file for changes.
   */
  private watchFile(filePath: string, level: ConfigLevel): void {
    try {
      const watcher = fs.watch(filePath, (eventType) => {
        if (eventType === 'change') {
          this.loadFromFile(filePath, level);
        }
      });
      this.watchers.push(watcher);
    } catch {
      // File might not exist or be unwatchable, ignore
    }
  }

  /**
   * Save configuration level to a file.
   */
  saveToFile(filePath: string, level: ConfigLevel): boolean {
    try {
      const levelConfig = this.levels.get(level);
      if (!levelConfig) {
        return false;
      }

      const dir = path.dirname(filePath);
      if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
      }

      fs.writeFileSync(filePath, JSON.stringify(levelConfig.values, null, 2));
      return true;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.emit({ type: 'config.error', level, error: `Failed to save to ${filePath}: ${message}` });
      return false;
    }
  }

  /**
   * Load all configuration levels from standard locations.
   */
  loadAll(): void {
    this.loadGlobal();
    this.loadWorkspace();
  }

  /**
   * Reload all configuration levels.
   */
  reload(): void {
    // Preserve session and override levels
    const session = this.levels.get('session');
    const override = this.levels.get('override');

    // Clear all except defaults
    const defaults = this.levels.get('default');
    this.levels.clear();
    if (defaults) {
      this.levels.set('default', defaults);
    }

    // Reload from files
    this.loadAll();

    // Restore session and override
    if (session) {
      this.levels.set('session', session);
    }
    if (override) {
      this.levels.set('override', override);
    }

    this.resolvedCache = null;
  }

  // ===========================================================================
  // EVENTS
  // ===========================================================================

  /**
   * Subscribe to configuration events.
   */
  subscribe(listener: ConfigEventListener): () => void {
    this.eventListeners.add(listener);
    return () => this.eventListeners.delete(listener);
  }

  /**
   * Emit a configuration event.
   */
  private emit(event: ConfigEvent): void {
    for (const listener of this.eventListeners) {
      try {
        listener(event);
      } catch {
        // Ignore listener errors
      }
    }
  }

  // ===========================================================================
  // UTILITIES
  // ===========================================================================

  /**
   * Get a diff between two levels.
   */
  diff(level1: ConfigLevel, level2: ConfigLevel): { added: string[]; removed: string[]; changed: string[] } {
    const config1 = this.levels.get(level1)?.values || {};
    const config2 = this.levels.get(level2)?.values || {};

    const added: string[] = [];
    const removed: string[] = [];
    const changed: string[] = [];

    const allKeys = new Set([...Object.keys(config1), ...Object.keys(config2)]);

    for (const key of allKeys) {
      const in1 = key in config1;
      const in2 = key in config2;

      if (!in1 && in2) {
        added.push(key);
      } else if (in1 && !in2) {
        removed.push(key);
      } else if (config1[key] !== config2[key]) {
        changed.push(key);
      }
    }

    return { added, removed, changed };
  }

  /**
   * Export resolved configuration as JSON string.
   */
  exportResolved(): string {
    return JSON.stringify(this.resolve().config, null, 2);
  }

  /**
   * Get info about loaded levels.
   */
  getLoadedLevels(): Array<{ level: ConfigLevel; source?: string; loadedAt: Date }> {
    return Array.from(this.levels.values()).map((l) => ({
      level: l.level,
      source: l.source,
      loadedAt: l.loadedAt,
    }));
  }

  /**
   * Reset to defaults only.
   */
  reset(): void {
    const defaults = this.levels.get('default');
    this.levels.clear();
    if (defaults) {
      this.levels.set('default', defaults);
    }
    this.resolvedCache = null;
  }

  /**
   * Cleanup resources (watchers, etc.).
   */
  cleanup(): void {
    for (const watcher of this.watchers) {
      watcher.close();
    }
    this.watchers = [];
    this.eventListeners.clear();
  }
}

// =============================================================================
// FACTORY FUNCTIONS
// =============================================================================

/**
 * Create a hierarchical config manager.
 */
export function createHierarchicalConfig<T extends Record<string, unknown>>(
  defaults?: Partial<T>,
  options?: HierarchicalConfigOptions
): HierarchicalConfigManager<T> {
  return new HierarchicalConfigManager<T>(defaults, options);
}

/**
 * Create a config manager and load from standard locations.
 */
export function createAndLoadConfig<T extends Record<string, unknown>>(
  defaults?: Partial<T>,
  workspaceDir?: string
): HierarchicalConfigManager<T> {
  return new HierarchicalConfigManager<T>(defaults, {
    workspaceDir,
    autoLoad: true,
  });
}

// =============================================================================
// SAMPLE CONFIG
// =============================================================================

/**
 * Get a sample global config for documentation.
 */
export function getSampleGlobalConfig(): Record<string, unknown> {
  return {
    // Model preferences
    model: 'anthropic/claude-sonnet-4',
    maxIterations: 50,
    timeout: 300000,

    // Feature toggles
    memory: { enabled: true },
    planning: { enabled: true, autoplan: true },
    reflection: { enabled: true },

    // Safety settings
    sandbox: {
      enabled: true,
      // Operational sandbox limits (low-level)
      allowedCommands: ['node', 'npm', 'npx', 'git', 'ls', 'cat'],
    },
    // Preferred policy model (high-level behavior)
    policyEngine: {
      enabled: true,
      defaultProfile: 'code-full',
    },
    humanInLoop: { enabled: true, riskThreshold: 'high' },

    // Resource limits
    resources: {
      maxMemoryMB: 512,
      maxCpuTimeSec: 300,
    },
  };
}

/**
 * Get a sample workspace config for documentation.
 */
export function getSampleWorkspaceConfig(): Record<string, unknown> {
  return {
    // Project-specific overrides
    systemPrompt: 'You are a helpful assistant working on this specific project.',

    // Project-specific tool allowlists
    sandbox: {
      allowedPaths: ['.', './src', './tests'],
      allowedCommands: ['npm', 'npx', 'node', 'tsc', 'eslint', 'prettier'],
    },
    policyEngine: {
      profiles: {
        'project-safe': {
          toolAccessMode: 'whitelist',
          allowedTools: ['read_file', 'write_file', 'edit_file', 'glob', 'grep', 'bash'],
          bashMode: 'read_only',
          bashWriteProtection: 'block_file_mutation',
        },
      },
      defaultProfile: 'project-safe',
    },

    // Project context
    rules: {
      sources: [{ type: 'file', path: 'CLAUDE.md', priority: 1 }],
    },
  };
}

/**
 * Ensure config directories exist.
 */
export function ensureConfigDirectories(): void {
  const globalDir = path.join(homedir(), '.agent');
  if (!fs.existsSync(globalDir)) {
    fs.mkdirSync(globalDir, { recursive: true });
  }
}
