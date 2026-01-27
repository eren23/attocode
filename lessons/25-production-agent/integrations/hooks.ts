/**
 * Lesson 23: Hooks Integration
 *
 * Integrates the hook system (Lesson 10-11) into the production agent.
 * Provides event emission and interception capabilities.
 */

import type {
  HooksConfig,
  PluginsConfig,
  Hook,
  HookEvent,
  Plugin,
  PluginContext,
  ToolDefinition,
  AgentEvent,
  AgentEventListener,
} from '../types.js';

// =============================================================================
// HOOK MANAGER
// =============================================================================

/**
 * Manages hooks and plugins for the agent.
 */
export class HookManager {
  private hooks: Map<HookEvent, Hook[]> = new Map();
  private plugins: Map<string, Plugin> = new Map();
  private tools: Map<string, ToolDefinition> = new Map();
  private listeners: Set<AgentEventListener> = new Set();
  private config: { hooks: HooksConfig; plugins: PluginsConfig };

  constructor(hooksConfig: HooksConfig, pluginsConfig: PluginsConfig) {
    this.config = { hooks: hooksConfig, plugins: pluginsConfig };
    this.initializeBuiltInHooks();
  }

  /**
   * Initialize built-in hooks based on config.
   */
  private initializeBuiltInHooks(): void {
    const builtIn = this.config.hooks.builtIn || {};

    if (builtIn.logging) {
      this.registerHook({
        event: 'llm.before',
        handler: (data) => {
          const d = data as { model?: string };
          console.log(`[Hook] LLM call starting (model: ${d.model || 'unknown'})`);
        },
        priority: 100,
      });

      this.registerHook({
        event: 'tool.before',
        handler: (data) => {
          const d = data as { tool?: string };
          console.log(`[Hook] Tool call: ${d.tool || 'unknown'}`);
        },
        priority: 100,
      });
    }

    if (builtIn.timing) {
      const startTimes = new Map<string, number>();

      this.registerHook({
        event: 'llm.before',
        handler: () => {
          startTimes.set('llm', Date.now());
        },
        priority: 99,
      });

      this.registerHook({
        event: 'llm.after',
        handler: () => {
          const start = startTimes.get('llm');
          if (start) {
            console.log(`[Hook] LLM call took ${Date.now() - start}ms`);
            startTimes.delete('llm');
          }
        },
        priority: 99,
      });
    }

    // Register custom hooks from config
    for (const hook of this.config.hooks.custom || []) {
      this.registerHook(hook);
    }
  }

  /**
   * Register a hook.
   */
  registerHook(hook: Hook): void {
    const existing = this.hooks.get(hook.event) || [];

    // Check for duplicate by ID or handler reference
    if (hook.id && existing.some((h) => h.id === hook.id)) {
      console.warn(`[Hook] Hook "${hook.id}" already registered for ${hook.event}`);
      return;
    }
    if (existing.some((h) => h.handler === hook.handler)) {
      console.warn(`[Hook] Duplicate handler already registered for ${hook.event}`);
      return;
    }

    existing.push(hook);
    // Sort by priority (lower = higher priority)
    existing.sort((a, b) => (a.priority || 50) - (b.priority || 50));
    this.hooks.set(hook.event, existing);
  }

  /**
   * Unregister a hook.
   */
  unregisterHook(event: HookEvent, handler: Hook['handler']): void {
    const existing = this.hooks.get(event) || [];
    const index = existing.findIndex((h) => h.handler === handler);
    if (index !== -1) {
      existing.splice(index, 1);
      this.hooks.set(event, existing);
    }
  }

  /**
   * Execute hooks for an event.
   */
  async executeHooks(event: HookEvent, data: unknown): Promise<void> {
    const hooks = this.hooks.get(event) || [];

    for (const hook of hooks) {
      try {
        await hook.handler(data);
      } catch (err) {
        console.error(`[Hook] Error in ${event} hook:`, err);
      }
    }
  }

  /**
   * Load and initialize a plugin.
   */
  async loadPlugin(plugin: Plugin): Promise<void> {
    if (this.plugins.has(plugin.name)) {
      console.warn(`[Plugin] ${plugin.name} already loaded`);
      return;
    }

    const context: PluginContext = {
      registerHook: (hook) => this.registerHook(hook),
      registerTool: (tool) => this.tools.set(tool.name, tool),
      getConfig: <T>(key: string) => {
        // Simple config access
        return undefined as T;
      },
      log: (level, message) => {
        console.log(`[Plugin:${plugin.name}] [${level}] ${message}`);
      },
    };

    try {
      await plugin.initialize(context);
      this.plugins.set(plugin.name, plugin);
      console.log(`[Plugin] Loaded: ${plugin.name} v${plugin.version}`);
    } catch (err) {
      console.error(`[Plugin] Failed to load ${plugin.name}:`, err);
      throw err;
    }
  }

  /**
   * Unload a plugin.
   */
  async unloadPlugin(name: string): Promise<void> {
    const plugin = this.plugins.get(name);
    if (!plugin) return;

    if (plugin.cleanup) {
      await plugin.cleanup();
    }

    this.plugins.delete(name);
    console.log(`[Plugin] Unloaded: ${name}`);
  }

  /**
   * Get tools registered by plugins.
   */
  getPluginTools(): ToolDefinition[] {
    return Array.from(this.tools.values());
  }

  /**
   * Subscribe to agent events.
   */
  subscribe(listener: AgentEventListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /**
   * Emit an agent event.
   */
  emit(event: AgentEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch (err) {
        console.error('[Hook] Event listener error:', err);
      }
    }

    // Map agent events to hook events
    const hookEvent = this.mapToHookEvent(event);
    if (hookEvent) {
      this.executeHooks(hookEvent, event);
    }
  }

  /**
   * Map agent event to hook event.
   */
  private mapToHookEvent(event: AgentEvent): HookEvent | null {
    switch (event.type) {
      case 'start':
        return 'agent.start';
      case 'complete':
        return 'agent.end';
      case 'llm.start':
        return 'llm.before';
      case 'llm.complete':
        return 'llm.after';
      case 'tool.start':
        return 'tool.before';
      case 'tool.complete':
        return 'tool.after';
      case 'error':
        return 'error';
      default:
        return null;
    }
  }

  /**
   * Initialize all configured plugins.
   */
  async initializePlugins(): Promise<void> {
    for (const plugin of this.config.plugins.plugins || []) {
      await this.loadPlugin(plugin);
    }
  }

  /**
   * Cleanup all plugins.
   */
  async cleanup(): Promise<void> {
    for (const name of this.plugins.keys()) {
      await this.unloadPlugin(name);
    }
  }
}

// =============================================================================
// FACTORY
// =============================================================================

export function createHookManager(
  hooksConfig: HooksConfig,
  pluginsConfig: PluginsConfig
): HookManager {
  return new HookManager(hooksConfig, pluginsConfig);
}
