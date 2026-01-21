/**
 * Lesson 11: Plugin Context
 *
 * The plugin context provides a sandboxed interface for plugins
 * to interact with the agent. Plugins cannot access each other
 * directly - they communicate through events and shared services.
 *
 * Key design decisions:
 * - Resource tracking: We track everything a plugin registers
 *   so we can clean up properly when the plugin is unloaded
 * - Scoped storage: Each plugin gets its own namespace
 * - Controlled access: Plugins can only access approved services
 */

import type {
  PluginContext,
  PluginMetadata,
  PluginResources,
  LogLevel,
  ServiceName,
  HookRegistrationOptions,
  AgentEventType,
  ToolDefinition,
} from './types.js';
import type { HookRegistry } from '../10-hook-system/hook-registry.js';
import type { EventBus } from '../10-hook-system/event-bus.js';
import chalk from 'chalk';

// =============================================================================
// PLUGIN CONTEXT IMPLEMENTATION
// =============================================================================

/**
 * Services available to plugins.
 */
export interface PluginServices {
  hookRegistry: HookRegistry;
  eventBus: EventBus;
  toolRegistry: ToolRegistry;
  storage: StorageService;
  config: ConfigService;
}

/**
 * Simple tool registry interface.
 */
export interface ToolRegistry {
  register(tool: ToolDefinition): void;
  unregister(name: string): boolean;
  list(): string[];
}

/**
 * Simple storage service interface.
 */
export interface StorageService {
  set(namespace: string, key: string, value: unknown): Promise<void>;
  get<T>(namespace: string, key: string): Promise<T | undefined>;
  delete(namespace: string, key: string): Promise<boolean>;
}

/**
 * Simple config service interface.
 */
export interface ConfigService {
  get<T>(namespace: string, key: string): T | undefined;
  set<T>(namespace: string, key: string, value: T): void;
}

/**
 * Create a plugin context for a specific plugin.
 *
 * @param metadata - The plugin's metadata
 * @param services - Agent services to expose
 * @param resources - Resource tracker for cleanup
 */
export function createPluginContext(
  metadata: PluginMetadata,
  services: PluginServices,
  resources: PluginResources
): PluginContext {
  const namespace = metadata.name;

  // Generate unique hook IDs for this plugin
  let hookCounter = 0;
  const generateHookId = () => `${namespace}:hook-${++hookCounter}`;

  return {
    // ─── Metadata ────────────────────────────────────────────────────────────
    metadata,

    // ─── Hook Registration ───────────────────────────────────────────────────
    registerHook<T extends AgentEventType>(
      event: T,
      handler: (event: any) => void | Promise<void>,
      options?: HookRegistrationOptions
    ): void {
      const hookId = generateHookId();

      const unregister = services.hookRegistry.on(event, handler, {
        ...options,
        description: options?.description ?? `[${namespace}] ${event} hook`,
      });

      // Track for cleanup
      resources.hooks.push(hookId);

      // Store unregister function keyed by hook ID
      (resources as any)[`hook:${hookId}`] = unregister;
    },

    unregisterHook(hookId: string): boolean {
      const unregister = (resources as any)[`hook:${hookId}`];
      if (unregister) {
        unregister();
        delete (resources as any)[`hook:${hookId}`];
        const index = resources.hooks.indexOf(hookId);
        if (index !== -1) {
          resources.hooks.splice(index, 1);
        }
        return true;
      }
      return services.hookRegistry.unregister(hookId);
    },

    // ─── Tool Registration ───────────────────────────────────────────────────
    registerTool(tool: ToolDefinition): void {
      // Prefix tool name with plugin namespace to avoid conflicts
      const namespacedTool = {
        ...tool,
        name: `${namespace}:${tool.name}`,
        description: `[${namespace}] ${tool.description}`,
      };

      services.toolRegistry.register(namespacedTool as ToolDefinition);
      resources.tools.push(namespacedTool.name);
    },

    unregisterTool(toolName: string): boolean {
      const fullName = toolName.includes(':') ? toolName : `${namespace}:${toolName}`;
      const result = services.toolRegistry.unregister(fullName);

      if (result) {
        const index = resources.tools.indexOf(fullName);
        if (index !== -1) {
          resources.tools.splice(index, 1);
        }
      }

      return result;
    },

    getAvailableTools(): string[] {
      return services.toolRegistry.list();
    },

    // ─── Configuration ───────────────────────────────────────────────────────
    getConfig<T>(key: string, defaultValue?: T): T | undefined {
      const value = services.config.get<T>(namespace, key);
      return value !== undefined ? value : defaultValue;
    },

    setConfig<T>(key: string, value: T): void {
      services.config.set(namespace, key, value);
      if (!resources.configKeys.includes(key)) {
        resources.configKeys.push(key);
      }
    },

    // ─── Logging ─────────────────────────────────────────────────────────────
    log(level: LogLevel, message: string, data?: unknown): void {
      const prefix = `[${namespace}]`;
      const timestamp = new Date().toISOString();

      let colorFn: typeof chalk.white;
      switch (level) {
        case 'debug':
          colorFn = chalk.gray;
          break;
        case 'info':
          colorFn = chalk.blue;
          break;
        case 'warn':
          colorFn = chalk.yellow;
          break;
        case 'error':
          colorFn = chalk.red;
          break;
        default:
          colorFn = chalk.white;
      }

      const formattedMessage = `${timestamp} ${colorFn(level.toUpperCase().padEnd(5))} ${chalk.cyan(prefix)} ${message}`;

      if (data !== undefined) {
        console.log(formattedMessage, data);
      } else {
        console.log(formattedMessage);
      }
    },

    // ─── Storage ─────────────────────────────────────────────────────────────
    async store(key: string, value: unknown): Promise<void> {
      await services.storage.set(namespace, key, value);
      if (!resources.storageKeys.includes(key)) {
        resources.storageKeys.push(key);
      }
    },

    async retrieve<T>(key: string): Promise<T | undefined> {
      return services.storage.get<T>(namespace, key);
    },

    async delete(key: string): Promise<boolean> {
      const result = await services.storage.delete(namespace, key);
      if (result) {
        const index = resources.storageKeys.indexOf(key);
        if (index !== -1) {
          resources.storageKeys.splice(index, 1);
        }
      }
      return result;
    },

    // ─── Inter-Plugin Communication ──────────────────────────────────────────
    emit(eventName: string, data: unknown): void {
      services.eventBus.emitSync({
        type: 'custom',
        name: `${namespace}:${eventName}`,
        data,
      });
    },

    subscribe(eventName: string, handler: (data: unknown) => void): () => void {
      const subscription = services.eventBus.on('custom', (event) => {
        if (event.name === eventName || event.name === `${namespace}:${eventName}`) {
          handler(event.data);
        }
      });

      const unsubscribe = () => subscription.unsubscribe();
      resources.subscriptions.push(unsubscribe);

      return unsubscribe;
    },

    // ─── Agent Services ──────────────────────────────────────────────────────
    getService<T>(serviceName: string): T | undefined {
      // Only expose approved services
      const allowedServices: ServiceName[] = [
        'hookRegistry',
        'toolRegistry',
        'eventBus',
        'storage',
        'config',
      ];

      if (!allowedServices.includes(serviceName as ServiceName)) {
        console.warn(`[${namespace}] Attempted to access unauthorized service: ${serviceName}`);
        return undefined;
      }

      return (services as any)[serviceName] as T | undefined;
    },
  };
}

// =============================================================================
// IN-MEMORY IMPLEMENTATIONS
// =============================================================================

/**
 * Simple in-memory tool registry for demonstration.
 */
export class InMemoryToolRegistry implements ToolRegistry {
  private tools: Map<string, ToolDefinition> = new Map();

  register(tool: ToolDefinition): void {
    if (this.tools.has(tool.name)) {
      console.warn(`Tool "${tool.name}" is being overwritten`);
    }
    this.tools.set(tool.name, tool);
  }

  unregister(name: string): boolean {
    return this.tools.delete(name);
  }

  list(): string[] {
    return [...this.tools.keys()];
  }

  get(name: string): ToolDefinition | undefined {
    return this.tools.get(name);
  }
}

/**
 * Simple in-memory storage for demonstration.
 */
export class InMemoryStorage implements StorageService {
  private data: Map<string, Map<string, unknown>> = new Map();

  async set(namespace: string, key: string, value: unknown): Promise<void> {
    let nsData = this.data.get(namespace);
    if (!nsData) {
      nsData = new Map();
      this.data.set(namespace, nsData);
    }
    nsData.set(key, value);
  }

  async get<T>(namespace: string, key: string): Promise<T | undefined> {
    return this.data.get(namespace)?.get(key) as T | undefined;
  }

  async delete(namespace: string, key: string): Promise<boolean> {
    const nsData = this.data.get(namespace);
    if (!nsData) return false;
    return nsData.delete(key);
  }

  // Clear all data for a namespace (used during plugin cleanup)
  async clearNamespace(namespace: string): Promise<void> {
    this.data.delete(namespace);
  }
}

/**
 * Simple in-memory configuration for demonstration.
 */
export class InMemoryConfig implements ConfigService {
  private config: Map<string, Map<string, unknown>> = new Map();

  get<T>(namespace: string, key: string): T | undefined {
    return this.config.get(namespace)?.get(key) as T | undefined;
  }

  set<T>(namespace: string, key: string, value: T): void {
    let nsConfig = this.config.get(namespace);
    if (!nsConfig) {
      nsConfig = new Map();
      this.config.set(namespace, nsConfig);
    }
    nsConfig.set(key, value);
  }

  // Clear config for a namespace (used during plugin cleanup)
  clearNamespace(namespace: string): void {
    this.config.delete(namespace);
  }
}

// =============================================================================
// RESOURCE CLEANUP
// =============================================================================

/**
 * Clean up all resources registered by a plugin.
 */
export async function cleanupPluginResources(
  resources: PluginResources,
  services: PluginServices,
  namespace: string
): Promise<void> {
  // Unsubscribe from events
  for (const unsubscribe of resources.subscriptions) {
    try {
      unsubscribe();
    } catch (err) {
      console.error(`Error unsubscribing event in plugin ${namespace}:`, err);
    }
  }

  // Unregister hooks
  for (const hookId of resources.hooks) {
    const unregister = (resources as any)[`hook:${hookId}`];
    if (unregister) {
      try {
        unregister();
      } catch (err) {
        console.error(`Error unregistering hook ${hookId}:`, err);
      }
    }
  }

  // Unregister tools
  for (const toolName of resources.tools) {
    try {
      services.toolRegistry.unregister(toolName);
    } catch (err) {
      console.error(`Error unregistering tool ${toolName}:`, err);
    }
  }

  // Clear storage and config
  if (services.storage instanceof InMemoryStorage) {
    await services.storage.clearNamespace(namespace);
  }

  if (services.config instanceof InMemoryConfig) {
    services.config.clearNamespace(namespace);
  }
}

/**
 * Create empty plugin resources for tracking.
 */
export function createPluginResources(): PluginResources {
  return {
    hooks: [],
    tools: [],
    configKeys: [],
    storageKeys: [],
    subscriptions: [],
  };
}
