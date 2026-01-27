/**
 * Lesson 11: Plugin Manager
 *
 * The plugin manager is the central coordinator for all plugins.
 * It handles:
 * - Plugin registration and loading
 * - Lifecycle management (init, cleanup)
 * - Dependency resolution
 * - Event notification for plugin state changes
 */

import type {
  Plugin,
  PluginMetadata,
  PluginState,
  LoadedPlugin,
  PluginLoadOptions,
  PluginSource,
  PluginManagerEvent,
  PluginManagerEventListener,
  PluginResources,
} from './types.js';
import {
  createPluginContext,
  createPluginResources,
  cleanupPluginResources,
  InMemoryToolRegistry,
  InMemoryStorage,
  InMemoryConfig,
  type PluginServices,
} from './plugin-context.js';
import {
  loadPlugin,
  checkDependencies,
  sortByDependencies,
  validatePlugin,
} from './plugin-loader.js';
import { HookRegistry } from '../10-hook-system/hook-registry.js';
import { EventBus } from '../10-hook-system/event-bus.js';
import chalk from 'chalk';

// =============================================================================
// PLUGIN MANAGER
// =============================================================================

/**
 * Configuration for the plugin manager.
 */
export interface PluginManagerConfig {
  /** Check dependencies before loading */
  checkDependencies: boolean;

  /** Timeout for plugin initialization (ms) */
  initTimeout: number;

  /** Enable debug logging */
  debug: boolean;

  /** Auto-enable plugins after loading */
  autoEnable: boolean;
}

const DEFAULT_CONFIG: PluginManagerConfig = {
  checkDependencies: true,
  initTimeout: 5000,
  debug: false,
  autoEnable: true,
};

/**
 * Plugin manager handles the lifecycle of all plugins.
 *
 * Example usage:
 * ```ts
 * const manager = new PluginManager();
 *
 * // Register and load a plugin
 * await manager.register(myPlugin);
 *
 * // Enable the plugin
 * await manager.enable('my-plugin');
 *
 * // Later, disable and unload
 * await manager.disable('my-plugin');
 * await manager.unregister('my-plugin');
 * ```
 */
export class PluginManager {
  // Loaded plugins by name
  private plugins: Map<string, LoadedPlugin> = new Map();

  // Event listeners
  private listeners: Set<PluginManagerEventListener> = new Set();

  // Configuration
  private config: PluginManagerConfig;

  // Shared services for all plugins
  private services: PluginServices;

  constructor(config: Partial<PluginManagerConfig> = {}) {
    this.config = { ...DEFAULT_CONFIG, ...config };

    // Create shared services
    this.services = {
      hookRegistry: new HookRegistry({
        debug: this.config.debug,
        trackPerformance: true,
      }),
      eventBus: new EventBus(),
      toolRegistry: new InMemoryToolRegistry(),
      storage: new InMemoryStorage(),
      config: new InMemoryConfig(),
    };
  }

  // =============================================================================
  // REGISTRATION
  // =============================================================================

  /**
   * Register a plugin directly.
   */
  async register(plugin: Plugin, options?: PluginLoadOptions): Promise<boolean> {
    return this.registerFromSource({ type: 'object', plugin }, options);
  }

  /**
   * Register a plugin from a source.
   */
  async registerFromSource(
    source: PluginSource,
    options: PluginLoadOptions = {}
  ): Promise<boolean> {
    // Load the plugin
    const loadResult = await loadPlugin(source, options);

    if (!loadResult.success || !loadResult.plugin) {
      this.log('error', `Failed to load plugin: ${loadResult.error?.message}`);
      return false;
    }

    const { plugin: loadedPlugin } = loadResult;
    const name = loadedPlugin.plugin.metadata.name;

    // Check if already registered
    if (this.plugins.has(name)) {
      this.log('warn', `Plugin "${name}" is already registered`);
      return false;
    }

    // Check dependencies
    if (this.config.checkDependencies) {
      const depCheck = checkDependencies(
        loadedPlugin.plugin,
        new Map([...this.plugins.entries()].map(([n, lp]) => [n, lp.plugin]))
      );

      if (!depCheck.satisfied) {
        this.log('error', `Plugin "${name}" has missing dependencies: ${depCheck.missing.join(', ')}`);
        return false;
      }
    }

    // Register
    this.plugins.set(name, loadedPlugin);
    this.emit({ type: 'plugin.registered', name, metadata: loadedPlugin.plugin.metadata });
    this.log('info', `Plugin "${name}" registered`);

    // Auto-enable if configured
    if (this.config.autoEnable) {
      await this.enable(name);
    }

    return true;
  }

  /**
   * Unregister a plugin.
   */
  async unregister(name: string): Promise<boolean> {
    const loaded = this.plugins.get(name);
    if (!loaded) {
      this.log('warn', `Plugin "${name}" is not registered`);
      return false;
    }

    // Disable first if active
    if (loaded.state === 'active') {
      await this.disable(name);
    }

    // Remove from registry
    this.plugins.delete(name);
    this.emit({ type: 'plugin.unloaded', name });
    this.log('info', `Plugin "${name}" unregistered`);

    return true;
  }

  // =============================================================================
  // LIFECYCLE
  // =============================================================================

  /**
   * Enable a plugin (initialize and activate).
   */
  async enable(name: string): Promise<boolean> {
    const loaded = this.plugins.get(name);
    if (!loaded) {
      this.log('error', `Plugin "${name}" is not registered`);
      return false;
    }

    if (loaded.state === 'active') {
      this.log('warn', `Plugin "${name}" is already active`);
      return true;
    }

    // Set state to loading
    loaded.state = 'loading';
    this.emit({ type: 'plugin.loading', name });

    try {
      // Create plugin context
      const resources = createPluginResources();
      loaded.resources = resources;

      const context = createPluginContext(
        loaded.plugin.metadata,
        this.services,
        resources
      );

      // Initialize with timeout
      await Promise.race([
        loaded.plugin.initialize(context),
        this.timeout(this.config.initTimeout, name),
      ]);

      // Set state to active
      loaded.state = 'active';
      this.emit({ type: 'plugin.loaded', name, plugin: loaded });
      this.log('info', `Plugin "${name}" enabled`);

      return true;
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));
      loaded.state = 'error';
      loaded.error = error;

      this.emit({ type: 'plugin.error', name, error });
      this.log('error', `Plugin "${name}" failed to initialize: ${error.message}`);

      return false;
    }
  }

  /**
   * Disable a plugin (cleanup and deactivate).
   */
  async disable(name: string): Promise<boolean> {
    const loaded = this.plugins.get(name);
    if (!loaded) {
      this.log('error', `Plugin "${name}" is not registered`);
      return false;
    }

    if (loaded.state !== 'active') {
      this.log('warn', `Plugin "${name}" is not active`);
      return true;
    }

    // Set state to unloading
    loaded.state = 'unloading';
    this.emit({ type: 'plugin.unloading', name });

    try {
      // Call cleanup if provided
      if (loaded.plugin.cleanup) {
        await loaded.plugin.cleanup();
      }

      // Clean up resources
      await cleanupPluginResources(
        loaded.resources,
        this.services,
        name
      );

      // Set state to disabled
      loaded.state = 'disabled';
      this.emit({ type: 'plugin.disabled', name });
      this.log('info', `Plugin "${name}" disabled`);

      return true;
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));
      loaded.state = 'error';
      loaded.error = error;

      this.emit({ type: 'plugin.error', name, error });
      this.log('error', `Plugin "${name}" failed to cleanup: ${error.message}`);

      return false;
    }
  }

  /**
   * Reload a plugin (disable then enable).
   */
  async reload(name: string): Promise<boolean> {
    const loaded = this.plugins.get(name);
    if (!loaded) {
      this.log('error', `Plugin "${name}" is not registered`);
      return false;
    }

    if (loaded.state === 'active') {
      await this.disable(name);
    }

    return this.enable(name);
  }

  // =============================================================================
  // QUERIES
  // =============================================================================

  /**
   * Get a loaded plugin by name.
   */
  get(name: string): LoadedPlugin | undefined {
    return this.plugins.get(name);
  }

  /**
   * Get all loaded plugins.
   */
  getAll(): LoadedPlugin[] {
    return [...this.plugins.values()];
  }

  /**
   * Get all active plugins.
   */
  getActive(): LoadedPlugin[] {
    return this.getAll().filter((p) => p.state === 'active');
  }

  /**
   * Check if a plugin is registered.
   */
  has(name: string): boolean {
    return this.plugins.has(name);
  }

  /**
   * Get the state of a plugin.
   */
  getState(name: string): PluginState | undefined {
    return this.plugins.get(name)?.state;
  }

  /**
   * Get all plugin names.
   */
  names(): string[] {
    return [...this.plugins.keys()];
  }

  // =============================================================================
  // SERVICES ACCESS
  // =============================================================================

  /**
   * Get the shared services.
   * Useful for the agent core to access plugin-registered tools, hooks, etc.
   */
  getServices(): PluginServices {
    return this.services;
  }

  /**
   * Get the hook registry.
   */
  getHookRegistry(): HookRegistry {
    return this.services.hookRegistry;
  }

  /**
   * Get the event bus.
   */
  getEventBus(): EventBus {
    return this.services.eventBus;
  }

  // =============================================================================
  // EVENTS
  // =============================================================================

  /**
   * Subscribe to plugin manager events.
   */
  on(listener: PluginManagerEventListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /**
   * Emit an event to all listeners.
   */
  private emit(event: PluginManagerEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch (err) {
        console.error('Error in plugin manager listener:', err);
      }
    }
  }

  // =============================================================================
  // UTILITIES
  // =============================================================================

  /**
   * Get a summary of all plugins.
   */
  summary(): string {
    const lines: string[] = ['Plugin Manager Summary:', ''];

    if (this.plugins.size === 0) {
      lines.push('  No plugins registered');
    } else {
      for (const [name, loaded] of this.plugins) {
        const stateColor = this.stateColor(loaded.state);
        lines.push(
          `  ${chalk.bold(name)} v${loaded.plugin.metadata.version} - ${stateColor(loaded.state)}`
        );

        if (loaded.plugin.metadata.description) {
          lines.push(chalk.gray(`    ${loaded.plugin.metadata.description}`));
        }

        if (loaded.resources.hooks.length > 0) {
          lines.push(chalk.gray(`    Hooks: ${loaded.resources.hooks.length}`));
        }

        if (loaded.resources.tools.length > 0) {
          lines.push(chalk.gray(`    Tools: ${loaded.resources.tools.join(', ')}`));
        }

        if (loaded.error) {
          lines.push(chalk.red(`    Error: ${loaded.error.message}`));
        }
      }
    }

    return lines.join('\n');
  }

  /**
   * Shutdown all plugins.
   */
  async shutdown(): Promise<void> {
    this.log('info', 'Shutting down plugin manager...');

    // Disable all active plugins
    const activePlugins = this.getActive();
    for (const loaded of activePlugins) {
      await this.disable(loaded.plugin.metadata.name);
    }

    // Clear registry
    this.plugins.clear();
    this.listeners.clear();

    this.log('info', 'Plugin manager shutdown complete');
  }

  // =============================================================================
  // PRIVATE HELPERS
  // =============================================================================

  private timeout(ms: number, pluginName: string): Promise<never> {
    return new Promise((_, reject) => {
      setTimeout(() => {
        reject(new Error(`Plugin "${pluginName}" initialization timed out after ${ms}ms`));
      }, ms);
    });
  }

  private log(level: 'debug' | 'info' | 'warn' | 'error', message: string): void {
    if (level === 'debug' && !this.config.debug) return;

    const prefix = chalk.magenta('[PluginManager]');
    const colorFn = {
      debug: chalk.gray,
      info: chalk.blue,
      warn: chalk.yellow,
      error: chalk.red,
    }[level];

    console.log(`${prefix} ${colorFn(message)}`);
  }

  private stateColor(state: PluginState): (text: string) => string {
    switch (state) {
      case 'active':
        return chalk.green;
      case 'loading':
      case 'unloading':
        return chalk.yellow;
      case 'error':
        return chalk.red;
      case 'disabled':
        return chalk.gray;
      default:
        return chalk.white;
    }
  }
}

// =============================================================================
// GLOBAL INSTANCE
// =============================================================================

/**
 * Global plugin manager instance.
 */
export const globalPluginManager = new PluginManager();
