/**
 * Lesson 11: Plugin Loader
 *
 * Handles plugin discovery and loading from various sources:
 * - Direct objects (for testing and embedded plugins)
 * - File paths (local plugins)
 * - npm packages (third-party plugins)
 *
 * Key concepts:
 * - Validation before loading
 * - Dependency resolution
 * - Error handling for malformed plugins
 */

import type {
  Plugin,
  PluginMetadata,
  PluginSource,
  PluginLoadOptions,
  PluginLoadResult,
  PluginDiscoveryConfig,
  DiscoveredPlugin,
} from './types.js';
import * as path from 'path';
import * as fs from 'fs/promises';

// =============================================================================
// PLUGIN VALIDATION
// =============================================================================

/**
 * Validate plugin metadata.
 */
export function validatePluginMetadata(
  metadata: unknown
): { valid: boolean; errors: string[] } {
  const errors: string[] = [];

  if (!metadata || typeof metadata !== 'object') {
    return { valid: false, errors: ['Metadata must be an object'] };
  }

  const meta = metadata as Record<string, unknown>;

  // Required fields
  if (typeof meta.name !== 'string' || !meta.name) {
    errors.push('Plugin must have a name');
  } else if (!/^[a-z][a-z0-9-]*$/.test(meta.name)) {
    errors.push('Plugin name must be lowercase alphanumeric with hyphens');
  }

  if (typeof meta.version !== 'string' || !meta.version) {
    errors.push('Plugin must have a version');
  } else if (!/^\d+\.\d+\.\d+/.test(meta.version)) {
    errors.push('Plugin version must be semver format (x.y.z)');
  }

  // Optional fields validation
  if (meta.description !== undefined && typeof meta.description !== 'string') {
    errors.push('Plugin description must be a string');
  }

  if (meta.author !== undefined && typeof meta.author !== 'string') {
    errors.push('Plugin author must be a string');
  }

  if (meta.dependencies !== undefined) {
    if (!Array.isArray(meta.dependencies)) {
      errors.push('Plugin dependencies must be an array');
    } else {
      for (const dep of meta.dependencies) {
        if (!dep.name || !dep.version) {
          errors.push('Each dependency must have name and version');
        }
      }
    }
  }

  return { valid: errors.length === 0, errors };
}

/**
 * Validate a plugin object.
 */
export function validatePlugin(
  plugin: unknown
): { valid: boolean; errors: string[] } {
  const errors: string[] = [];

  if (!plugin || typeof plugin !== 'object') {
    return { valid: false, errors: ['Plugin must be an object'] };
  }

  const p = plugin as Record<string, unknown>;

  // Check for required properties
  if (!p.metadata) {
    errors.push('Plugin must have metadata');
  } else {
    const metaValidation = validatePluginMetadata(p.metadata);
    errors.push(...metaValidation.errors);
  }

  if (typeof p.initialize !== 'function') {
    errors.push('Plugin must have an initialize function');
  }

  // Optional cleanup should be a function if present
  if (p.cleanup !== undefined && typeof p.cleanup !== 'function') {
    errors.push('Plugin cleanup must be a function');
  }

  return { valid: errors.length === 0, errors };
}

// =============================================================================
// PLUGIN LOADING
// =============================================================================

/**
 * Load a plugin from a source.
 */
export async function loadPlugin(
  source: PluginSource,
  options: PluginLoadOptions = {}
): Promise<PluginLoadResult> {
  const { initTimeout = 5000 } = options;

  try {
    let plugin: Plugin;

    switch (source.type) {
      case 'object':
        plugin = source.plugin;
        break;

      case 'path':
        plugin = await loadFromPath(source.path);
        break;

      case 'package':
        plugin = await loadFromPackage(source.name);
        break;

      case 'url':
        return {
          success: false,
          error: new Error('URL loading not implemented'),
        };

      default:
        return {
          success: false,
          error: new Error(`Unknown source type: ${(source as any).type}`),
        };
    }

    // Validate
    const validation = validatePlugin(plugin);
    if (!validation.valid) {
      return {
        success: false,
        error: new Error(`Invalid plugin: ${validation.errors.join(', ')}`),
      };
    }

    return {
      success: true,
      plugin: {
        plugin,
        state: 'registered',
        loadedAt: new Date(),
        resources: {
          hooks: [],
          tools: [],
          configKeys: [],
          storageKeys: [],
          subscriptions: [],
        },
      },
    };
  } catch (err) {
    return {
      success: false,
      error: err instanceof Error ? err : new Error(String(err)),
    };
  }
}

/**
 * Load a plugin from a file path.
 */
async function loadFromPath(filePath: string): Promise<Plugin> {
  // Resolve to absolute path
  const absolutePath = path.isAbsolute(filePath)
    ? filePath
    : path.resolve(process.cwd(), filePath);

  // Check if file exists
  try {
    await fs.access(absolutePath);
  } catch {
    throw new Error(`Plugin file not found: ${absolutePath}`);
  }

  // Dynamic import
  const module = await import(absolutePath);

  // Check for default export or plugin export
  const plugin = module.default ?? module.plugin ?? module;

  if (!plugin) {
    throw new Error(`No plugin found in ${filePath}`);
  }

  return plugin;
}

/**
 * Load a plugin from an npm package.
 */
async function loadFromPackage(packageName: string): Promise<Plugin> {
  try {
    const module = await import(packageName);
    const plugin = module.default ?? module.plugin ?? module;

    if (!plugin) {
      throw new Error(`No plugin found in package ${packageName}`);
    }

    return plugin;
  } catch (err) {
    if ((err as any).code === 'ERR_MODULE_NOT_FOUND') {
      throw new Error(`Package not found: ${packageName}. Try: npm install ${packageName}`);
    }
    throw err;
  }
}

// =============================================================================
// PLUGIN DISCOVERY
// =============================================================================

/**
 * Discover plugins in directories.
 */
export async function discoverPlugins(
  config: PluginDiscoveryConfig
): Promise<DiscoveredPlugin[]> {
  const discovered: DiscoveredPlugin[] = [];
  const {
    directories = [],
    patterns = ['**/plugin.{ts,js}', '**/*-plugin.{ts,js}'],
    recursive = true,
  } = config;

  for (const dir of directories) {
    try {
      const absoluteDir = path.isAbsolute(dir)
        ? dir
        : path.resolve(process.cwd(), dir);

      const files = await findPluginFiles(absoluteDir, patterns, recursive);

      for (const file of files) {
        const result = await probePlugin(file);
        discovered.push(result);
      }
    } catch (err) {
      console.error(`Error discovering plugins in ${dir}:`, err);
    }
  }

  // Check npm packages
  if (config.packages) {
    for (const packageName of config.packages) {
      discovered.push({
        source: { type: 'package', name: packageName },
        valid: true, // We can't validate without loading
      });
    }
  }

  return discovered;
}

/**
 * Find plugin files matching patterns.
 */
async function findPluginFiles(
  dir: string,
  patterns: string[],
  recursive: boolean
): Promise<string[]> {
  const files: string[] = [];

  try {
    const entries = await fs.readdir(dir, { withFileTypes: true });

    for (const entry of entries) {
      const fullPath = path.join(dir, entry.name);

      if (entry.isDirectory() && recursive) {
        const subFiles = await findPluginFiles(fullPath, patterns, recursive);
        files.push(...subFiles);
      } else if (entry.isFile()) {
        // Simple pattern matching (not full glob)
        for (const pattern of patterns) {
          const regex = patternToRegex(pattern);
          if (regex.test(entry.name)) {
            files.push(fullPath);
            break;
          }
        }
      }
    }
  } catch (err) {
    // Directory might not exist or be readable
  }

  return files;
}

/**
 * Convert a simple glob pattern to regex.
 */
function patternToRegex(pattern: string): RegExp {
  // Simple conversion - not full glob support
  const escaped = pattern
    .replace(/\./g, '\\.')
    .replace(/\*/g, '.*')
    .replace(/\{([^}]+)\}/g, (_, group) => `(${group.split(',').join('|')})`);

  return new RegExp(`^${escaped}$`);
}

/**
 * Probe a file to get plugin metadata without fully loading.
 */
async function probePlugin(filePath: string): Promise<DiscoveredPlugin> {
  try {
    // For now, we need to load the file to get metadata
    // In production, you might parse the file without executing
    const result = await loadPlugin({ type: 'path', path: filePath });

    if (result.success && result.plugin) {
      return {
        source: { type: 'path', path: filePath },
        metadata: result.plugin.plugin.metadata,
        valid: true,
      };
    }

    return {
      source: { type: 'path', path: filePath },
      valid: false,
      errors: [result.error?.message ?? 'Unknown error'],
    };
  } catch (err) {
    return {
      source: { type: 'path', path: filePath },
      valid: false,
      errors: [err instanceof Error ? err.message : String(err)],
    };
  }
}

// =============================================================================
// DEPENDENCY RESOLUTION
// =============================================================================

/**
 * Check if plugin dependencies are satisfied.
 */
export function checkDependencies(
  plugin: Plugin,
  loadedPlugins: Map<string, Plugin>
): { satisfied: boolean; missing: string[] } {
  const missing: string[] = [];

  if (!plugin.metadata.dependencies) {
    return { satisfied: true, missing };
  }

  for (const dep of plugin.metadata.dependencies) {
    const loadedDep = loadedPlugins.get(dep.name);

    if (!loadedDep) {
      if (!dep.optional) {
        missing.push(`${dep.name}@${dep.version}`);
      }
      continue;
    }

    // Simple version check (in production, use semver)
    if (!satisfiesVersion(loadedDep.metadata.version, dep.version)) {
      missing.push(`${dep.name}@${dep.version} (have ${loadedDep.metadata.version})`);
    }
  }

  return { satisfied: missing.length === 0, missing };
}

/**
 * Simple semver satisfaction check.
 * In production, use the 'semver' package.
 */
function satisfiesVersion(actual: string, required: string): boolean {
  // For now, just check major version match
  const actualParts = actual.split('.').map(Number);
  const requiredParts = required.split('.').map(Number);

  // If required starts with ^, allow minor/patch updates
  if (required.startsWith('^')) {
    return actualParts[0] === requiredParts[0];
  }

  // If required starts with ~, allow patch updates
  if (required.startsWith('~')) {
    return actualParts[0] === requiredParts[0] && actualParts[1] === requiredParts[1];
  }

  // Exact match
  return actual === required;
}

/**
 * Sort plugins by dependency order.
 */
export function sortByDependencies(plugins: Plugin[]): Plugin[] {
  const sorted: Plugin[] = [];
  const visited = new Set<string>();
  const visiting = new Set<string>();

  function visit(plugin: Plugin): void {
    const name = plugin.metadata.name;

    if (visited.has(name)) return;
    if (visiting.has(name)) {
      throw new Error(`Circular dependency detected: ${name}`);
    }

    visiting.add(name);

    // Visit dependencies first
    if (plugin.metadata.dependencies) {
      for (const dep of plugin.metadata.dependencies) {
        const depPlugin = plugins.find((p) => p.metadata.name === dep.name);
        if (depPlugin) {
          visit(depPlugin);
        }
      }
    }

    visiting.delete(name);
    visited.add(name);
    sorted.push(plugin);
  }

  for (const plugin of plugins) {
    visit(plugin);
  }

  return sorted;
}
