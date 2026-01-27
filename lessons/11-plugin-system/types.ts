/**
 * Lesson 11: Plugin System Types
 *
 * Type definitions for the plugin architecture.
 * Plugins extend agent functionality through a well-defined interface,
 * enabling modular, reusable, and isolated extensions.
 */

import type {
  Hook,
  AgentEventType,
  HookRegistrationOptions,
} from '../10-hook-system/types.js';
import type { ToolDefinition } from '../03-tool-system/types.js';

// =============================================================================
// PLUGIN DEFINITION
// =============================================================================

/**
 * Plugin metadata for identification and compatibility.
 */
export interface PluginMetadata {
  /** Unique identifier for the plugin */
  name: string;

  /** Semantic version (e.g., "1.2.3") */
  version: string;

  /** Human-readable description */
  description?: string;

  /** Plugin author */
  author?: string;

  /** Homepage or repository URL */
  url?: string;

  /** Required agent version (semver range) */
  agentVersion?: string;

  /** Plugin dependencies */
  dependencies?: PluginDependency[];

  /** Keywords for discovery */
  tags?: string[];
}

/**
 * A dependency on another plugin.
 */
export interface PluginDependency {
  /** Plugin name */
  name: string;

  /** Semver version range */
  version: string;

  /** Whether the dependency is optional */
  optional?: boolean;
}

/**
 * The main plugin interface.
 * Plugins must implement this to be loaded by the plugin manager.
 */
export interface Plugin {
  /** Plugin metadata */
  readonly metadata: PluginMetadata;

  /**
   * Initialize the plugin.
   * Called when the plugin is loaded.
   * Use the context to register hooks, tools, and access services.
   */
  initialize(context: PluginContext): Promise<void>;

  /**
   * Cleanup resources when the plugin is unloaded.
   * Optional but recommended for plugins that allocate resources.
   */
  cleanup?(): Promise<void>;

  /**
   * Called when the agent configuration changes.
   * Optional hook for plugins that need to react to config changes.
   */
  onConfigChange?(config: Record<string, unknown>): void;
}

// =============================================================================
// PLUGIN CONTEXT
// =============================================================================

/**
 * Context provided to plugins during initialization.
 * This is the plugin's interface to the agent - plugins should
 * ONLY interact with the agent through this context.
 */
export interface PluginContext {
  /** Plugin's own metadata */
  readonly metadata: PluginMetadata;

  // ─── Hook Registration ───────────────────────────────────────────────────

  /**
   * Register a hook for an event type.
   */
  registerHook<T extends AgentEventType>(
    event: T,
    handler: (event: any) => void | Promise<void>,
    options?: HookRegistrationOptions
  ): void;

  /**
   * Unregister a previously registered hook.
   */
  unregisterHook(hookId: string): boolean;

  // ─── Tool Registration ───────────────────────────────────────────────────

  /**
   * Register a new tool.
   */
  registerTool(tool: ToolDefinition): void;

  /**
   * Unregister a previously registered tool.
   */
  unregisterTool(toolName: string): boolean;

  /**
   * Get list of all available tools.
   */
  getAvailableTools(): string[];

  // ─── Configuration ───────────────────────────────────────────────────────

  /**
   * Get a configuration value.
   * Configurations are scoped to the plugin.
   */
  getConfig<T>(key: string): T | undefined;

  /**
   * Get a configuration value with a default.
   */
  getConfig<T>(key: string, defaultValue: T): T;

  /**
   * Set a configuration value.
   */
  setConfig<T>(key: string, value: T): void;

  // ─── Logging ─────────────────────────────────────────────────────────────

  /**
   * Log a message.
   * Messages are prefixed with the plugin name.
   */
  log(level: LogLevel, message: string, data?: unknown): void;

  // ─── Storage ─────────────────────────────────────────────────────────────

  /**
   * Store data persistently.
   * Data is scoped to the plugin.
   */
  store(key: string, value: unknown): Promise<void>;

  /**
   * Retrieve stored data.
   */
  retrieve<T>(key: string): Promise<T | undefined>;

  /**
   * Delete stored data.
   */
  delete(key: string): Promise<boolean>;

  // ─── Inter-Plugin Communication ──────────────────────────────────────────

  /**
   * Emit a custom event that other plugins can listen to.
   */
  emit(eventName: string, data: unknown): void;

  /**
   * Subscribe to custom events from other plugins.
   */
  subscribe(eventName: string, handler: (data: unknown) => void): () => void;

  // ─── Agent Services ──────────────────────────────────────────────────────

  /**
   * Get access to agent services.
   * Services provide controlled access to agent internals.
   */
  getService<T>(serviceName: string): T | undefined;
}

/**
 * Log levels for plugin logging.
 */
export type LogLevel = 'debug' | 'info' | 'warn' | 'error';

// =============================================================================
// PLUGIN LIFECYCLE
// =============================================================================

/**
 * Plugin state in its lifecycle.
 */
export type PluginState =
  | 'registered'    // Plugin is known but not loaded
  | 'loading'       // Currently initializing
  | 'active'        // Successfully loaded and running
  | 'error'         // Failed to load
  | 'disabled'      // Manually disabled
  | 'unloading';    // Currently cleaning up

/**
 * Information about a loaded plugin.
 */
export interface LoadedPlugin {
  /** The plugin instance */
  plugin: Plugin;

  /** Current state */
  state: PluginState;

  /** When the plugin was loaded */
  loadedAt: Date;

  /** Error if state is 'error' */
  error?: Error;

  /** Resources registered by this plugin */
  resources: PluginResources;
}

/**
 * Resources registered by a plugin.
 * Used for cleanup when the plugin is unloaded.
 */
export interface PluginResources {
  /** Hook IDs registered by this plugin */
  hooks: string[];

  /** Tool names registered by this plugin */
  tools: string[];

  /** Config keys set by this plugin */
  configKeys: string[];

  /** Storage keys used by this plugin */
  storageKeys: string[];

  /** Custom event subscriptions */
  subscriptions: (() => void)[];
}

// =============================================================================
// PLUGIN LOADER
// =============================================================================

/**
 * Options for loading plugins.
 */
export interface PluginLoadOptions {
  /** Verify plugin dependencies before loading */
  checkDependencies?: boolean;

  /** Timeout for plugin initialization in milliseconds */
  initTimeout?: number;

  /** Whether to enable the plugin immediately after loading */
  autoEnable?: boolean;

  /** Configuration to pass to the plugin */
  config?: Record<string, unknown>;
}

/**
 * Result of loading a plugin.
 */
export interface PluginLoadResult {
  success: boolean;
  plugin?: LoadedPlugin;
  error?: Error;
  warnings?: string[];
}

/**
 * Plugin source for dynamic loading.
 */
export type PluginSource =
  | { type: 'object'; plugin: Plugin }              // Direct object
  | { type: 'path'; path: string }                  // File path
  | { type: 'package'; name: string }               // npm package
  | { type: 'url'; url: string };                   // Remote URL

// =============================================================================
// PLUGIN MANAGER EVENTS
// =============================================================================

/**
 * Events emitted by the plugin manager.
 */
export type PluginManagerEvent =
  | { type: 'plugin.registered'; name: string; metadata: PluginMetadata }
  | { type: 'plugin.loading'; name: string }
  | { type: 'plugin.loaded'; name: string; plugin: LoadedPlugin }
  | { type: 'plugin.error'; name: string; error: Error }
  | { type: 'plugin.unloading'; name: string }
  | { type: 'plugin.unloaded'; name: string }
  | { type: 'plugin.disabled'; name: string }
  | { type: 'plugin.enabled'; name: string };

/**
 * Listener for plugin manager events.
 */
export type PluginManagerEventListener = (event: PluginManagerEvent) => void;

// =============================================================================
// PLUGIN DISCOVERY
// =============================================================================

/**
 * Configuration for plugin discovery.
 */
export interface PluginDiscoveryConfig {
  /** Directories to search for plugins */
  directories?: string[];

  /** File patterns to match (glob) */
  patterns?: string[];

  /** Whether to search recursively */
  recursive?: boolean;

  /** Packages to check in node_modules */
  packages?: string[];
}

/**
 * Result of plugin discovery.
 */
export interface DiscoveredPlugin {
  /** Where the plugin was found */
  source: PluginSource;

  /** Plugin metadata (if available without loading) */
  metadata?: Partial<PluginMetadata>;

  /** Whether the plugin appears valid */
  valid: boolean;

  /** Validation errors if not valid */
  errors?: string[];
}

// =============================================================================
// BUILT-IN SERVICES
// =============================================================================

/**
 * Service names for getService().
 */
export type ServiceName =
  | 'hookRegistry'    // Access to hook system
  | 'toolRegistry'    // Access to tool system
  | 'eventBus'        // Access to event bus
  | 'storage'         // Persistent storage
  | 'config'          // Configuration system
  | 'logger';         // Logging system

// =============================================================================
// RE-EXPORTS
// =============================================================================

export type {
  Hook,
  AgentEventType,
  HookRegistrationOptions,
} from '../10-hook-system/types.js';

export type {
  ToolDefinition,
  ToolResult,
  DangerLevel,
} from '../03-tool-system/types.js';
