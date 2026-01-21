/**
 * Lesson 24: Hierarchical State Manager
 *
 * Manages configuration that cascades from global to local levels:
 * - Default (built-in defaults)
 * - Global (~/.agent/config.json)
 * - Workspace (.agent/config.json)
 * - Session (runtime overrides)
 *
 * Higher priority levels override lower ones.
 * Inspired by VS Code settings hierarchy and OpenCode patterns.
 */

import * as fs from 'fs';
import * as path from 'path';
import type {
  LevelConfig,
  ConfigLevel,
  ResolvedConfig,
  ConfigSchema,
  ConfigFieldDef,
  AdvancedPatternEvent,
  AdvancedPatternEventListener,
} from './types.js';

// =============================================================================
// HIERARCHICAL STATE MANAGER
// =============================================================================

/**
 * Manages hierarchical configuration state.
 */
export class HierarchicalStateManager<T extends Record<string, unknown> = Record<string, unknown>> {
  private levels: Map<ConfigLevel, LevelConfig> = new Map();
  private schema?: ConfigSchema;
  private eventListeners: Set<AdvancedPatternEventListener> = new Set();
  private resolvedCache: ResolvedConfig<T> | null = null;

  // Priority order (higher index = higher priority)
  private static readonly PRIORITY: ConfigLevel[] = [
    'default',
    'global',
    'workspace',
    'session',
    'override',
  ];

  constructor(defaults?: Partial<T>, schema?: ConfigSchema) {
    this.schema = schema;

    // Set up default level
    if (defaults) {
      this.setLevel('default', defaults as Record<string, unknown>, 'built-in');
    }
  }

  // ===========================================================================
  // LEVEL MANAGEMENT
  // ===========================================================================

  /**
   * Set configuration at a specific level.
   */
  setLevel(
    level: ConfigLevel,
    values: Record<string, unknown>,
    source?: string
  ): void {
    // Validate against schema if available
    if (this.schema) {
      this.validate(values);
    }

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
   * Remove a configuration level.
   */
  removeLevel(level: ConfigLevel): boolean {
    if (level === 'default') {
      return false; // Can't remove defaults
    }
    const removed = this.levels.delete(level);
    if (removed) {
      this.resolvedCache = null;
    }
    return removed;
  }

  /**
   * Update specific keys at a level.
   */
  updateLevel(
    level: ConfigLevel,
    updates: Partial<Record<string, unknown>>
  ): void {
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
      level: 'session',
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
      });
    }
  }

  /**
   * Clear a session override.
   */
  clearSessionOverride(key: keyof T): void {
    const session = this.levels.get('session');
    if (session) {
      delete session.values[key as string];
      this.resolvedCache = null;
    }
  }

  /**
   * Clear all session overrides.
   */
  clearSessionOverrides(): void {
    this.levels.delete('session');
    this.resolvedCache = null;
  }

  /**
   * Set an explicit override (absolute highest priority).
   */
  setOverride<K extends keyof T>(key: K, value: T[K]): void {
    const override = this.levels.get('override') || {
      level: 'override',
      values: {},
      loadedAt: new Date(),
    };

    override.values[key as string] = value;
    this.levels.set('override', override);
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
    for (const level of HierarchicalStateManager.PRIORITY) {
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
   * Get all values from a specific level.
   */
  getValuesAt(level: ConfigLevel): Record<string, unknown> {
    const levelConfig = this.levels.get(level);
    return levelConfig ? { ...levelConfig.values } : {};
  }

  // ===========================================================================
  // FILE LOADING
  // ===========================================================================

  /**
   * Load global configuration from file.
   */
  loadGlobal(filePath: string = '~/.agent/config.json'): boolean {
    const resolved = filePath.replace('~', process.env.HOME || '');
    return this.loadFromFile(resolved, 'global');
  }

  /**
   * Load workspace configuration from file.
   */
  loadWorkspace(workspacePath: string = '.'): boolean {
    const configPath = path.join(workspacePath, '.agent', 'config.json');
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
      return true;
    } catch (error) {
      console.error(`Failed to load config from ${filePath}:`, error);
      return false;
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
      console.error(`Failed to save config to ${filePath}:`, error);
      return false;
    }
  }

  /**
   * Load all configuration levels.
   */
  loadAll(workspacePath: string = '.'): void {
    this.loadGlobal();
    this.loadWorkspace(workspacePath);
  }

  // ===========================================================================
  // VALIDATION
  // ===========================================================================

  /**
   * Validate configuration against schema.
   */
  validate(values: Record<string, unknown>): ValidationResult {
    if (!this.schema) {
      return { valid: true, errors: [] };
    }

    const errors: ValidationError[] = [];

    // Check required fields
    for (const field of this.schema.required || []) {
      if (values[field] === undefined) {
        errors.push({
          field,
          message: `Required field '${field}' is missing`,
          type: 'required',
        });
      }
    }

    // Validate each field
    for (const [field, value] of Object.entries(values)) {
      const fieldDef = this.schema.fields[field];
      if (!fieldDef) continue;

      const fieldErrors = this.validateField(field, value, fieldDef);
      errors.push(...fieldErrors);
    }

    return {
      valid: errors.length === 0,
      errors,
    };
  }

  /**
   * Validate a single field.
   */
  private validateField(
    field: string,
    value: unknown,
    def: ConfigFieldDef
  ): ValidationError[] {
    const errors: ValidationError[] = [];

    // Type check
    const actualType = Array.isArray(value) ? 'array' : typeof value;
    if (actualType !== def.type) {
      errors.push({
        field,
        message: `Expected ${def.type} but got ${actualType}`,
        type: 'type',
      });
      return errors;
    }

    // Enum check
    if (def.enum && !def.enum.includes(value)) {
      errors.push({
        field,
        message: `Value must be one of: ${def.enum.join(', ')}`,
        type: 'enum',
      });
    }

    // Range check for numbers
    if (typeof value === 'number') {
      if (def.min !== undefined && value < def.min) {
        errors.push({
          field,
          message: `Value must be >= ${def.min}`,
          type: 'range',
        });
      }
      if (def.max !== undefined && value > def.max) {
        errors.push({
          field,
          message: `Value must be <= ${def.max}`,
          type: 'range',
        });
      }
    }

    return errors;
  }

  /**
   * Set the validation schema.
   */
  setSchema(schema: ConfigSchema): void {
    this.schema = schema;
  }

  // ===========================================================================
  // EVENTS
  // ===========================================================================

  /**
   * Subscribe to events.
   */
  subscribe(listener: AdvancedPatternEventListener): () => void {
    this.eventListeners.add(listener);
    return () => this.eventListeners.delete(listener);
  }

  /**
   * Emit an event.
   */
  private emit(event: AdvancedPatternEvent): void {
    for (const listener of this.eventListeners) {
      try {
        listener(event);
      } catch (error) {
        console.error('Event listener error:', error);
      }
    }
  }

  // ===========================================================================
  // UTILITIES
  // ===========================================================================

  /**
   * Get a diff between two levels.
   */
  diff(level1: ConfigLevel, level2: ConfigLevel): ConfigDiff {
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
   * Export resolved configuration as JSON.
   */
  exportResolved(): string {
    return JSON.stringify(this.resolve().config, null, 2);
  }

  /**
   * Export all levels for debugging.
   */
  exportAll(): string {
    const data: Record<string, unknown> = {};
    for (const [level, config] of this.levels) {
      data[level] = config.values;
    }
    return JSON.stringify(data, null, 2);
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
}

// =============================================================================
// TYPES
// =============================================================================

/**
 * Validation result.
 */
export interface ValidationResult {
  valid: boolean;
  errors: ValidationError[];
}

/**
 * Validation error.
 */
export interface ValidationError {
  field: string;
  message: string;
  type: 'required' | 'type' | 'enum' | 'range' | 'custom';
}

/**
 * Configuration diff.
 */
export interface ConfigDiff {
  added: string[];
  removed: string[];
  changed: string[];
}

// =============================================================================
// FACTORY FUNCTIONS
// =============================================================================

/**
 * Create a hierarchical state manager with defaults.
 */
export function createStateManager<T extends Record<string, unknown>>(
  defaults?: Partial<T>,
  schema?: ConfigSchema
): HierarchicalStateManager<T> {
  return new HierarchicalStateManager<T>(defaults, schema);
}

/**
 * Create a state manager and load from standard locations.
 */
export function createAndLoadStateManager<T extends Record<string, unknown>>(
  defaults?: Partial<T>,
  workspacePath: string = '.'
): HierarchicalStateManager<T> {
  const manager = new HierarchicalStateManager<T>(defaults);
  manager.loadAll(workspacePath);
  return manager;
}

// =============================================================================
// COMMON SCHEMAS
// =============================================================================

/**
 * Schema for agent configuration.
 */
export const AGENT_CONFIG_SCHEMA: ConfigSchema = {
  version: '1.0',
  fields: {
    model: {
      type: 'string',
      description: 'Default model to use',
      default: 'claude-3-5-sonnet',
    },
    maxTokens: {
      type: 'number',
      description: 'Maximum tokens per response',
      default: 4096,
      min: 1,
      max: 100000,
    },
    temperature: {
      type: 'number',
      description: 'Sampling temperature',
      default: 0.7,
      min: 0,
      max: 2,
    },
    systemPrompt: {
      type: 'string',
      description: 'System prompt for the agent',
    },
    tools: {
      type: 'array',
      description: 'Enabled tools',
    },
    maxIterations: {
      type: 'number',
      description: 'Maximum agent loop iterations',
      default: 10,
      min: 1,
      max: 100,
    },
    timeout: {
      type: 'number',
      description: 'Request timeout in ms',
      default: 30000,
      min: 1000,
    },
    verbose: {
      type: 'boolean',
      description: 'Enable verbose logging',
      default: false,
    },
  },
  required: [],
};
