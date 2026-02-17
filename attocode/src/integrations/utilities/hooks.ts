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
  ShellHookCommand,
  Plugin,
  PluginContext,
  ToolDefinition,
  AgentEvent,
  AgentEventListener,
} from '../../types.js';
import { logger } from './logger.js';
import { spawn } from 'node:child_process';

// =============================================================================
// HOOK MANAGER
// =============================================================================

/**
 * Hook error record for observability.
 */
export interface HookError {
  event: HookEvent;
  error: Error;
  timestamp: Date;
  hookId?: string;
}

/**
 * Hook error listener type.
 */
export type HookErrorListener = (error: HookError) => void;

/**
 * Manages hooks and plugins for the agent.
 */
export class HookManager {
  private hooks: Map<HookEvent, Hook[]> = new Map();
  private plugins: Map<string, Plugin> = new Map();
  private tools: Map<string, ToolDefinition> = new Map();
  private listeners: Set<AgentEventListener> = new Set();
  private config: { hooks: HooksConfig; plugins: PluginsConfig };

  // Async hook tracking for error handling and cleanup
  private pendingHooks: Set<Promise<void>> = new Set();
  private hookErrors: HookError[] = [];
  private errorListeners: Set<HookErrorListener> = new Set();
  private maxHookErrors = 100; // Bounded error history

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
          logger.debug('Hook: LLM call starting', { model: d.model || 'unknown' });
        },
        priority: 100,
      });

      this.registerHook({
        event: 'tool.before',
        handler: (data) => {
          const d = data as { tool?: string };
          logger.debug('Hook: Tool call', { tool: d.tool || 'unknown' });
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
            logger.debug('Hook: LLM call completed', { durationMs: Date.now() - start });
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

    this.registerShellHooks();
  }

  private registerShellHooks(): void {
    const shellCfg = this.config.hooks.shell;
    if (!shellCfg?.enabled || !shellCfg.commands?.length) {
      return;
    }

    for (const cmd of shellCfg.commands) {
      this.registerHook({
        id: cmd.id || `shell:${cmd.event}:${cmd.command}`,
        event: cmd.event,
        priority: cmd.priority ?? 60,
        handler: (data) => this.executeShellHook(cmd, data),
      });
    }
  }

  private executeShellHook(commandConfig: ShellHookCommand, data: unknown): Promise<void> {
    return new Promise((resolve, reject) => {
      const shellCfg = this.config.hooks.shell || {};
      const timeoutMs = commandConfig.timeoutMs ?? shellCfg.defaultTimeoutMs ?? 5000;

      const baseEnvKeys = ['PATH', 'HOME', 'SHELL', 'TMPDIR', 'USER'];
      const env: Record<string, string> = {};
      for (const key of baseEnvKeys) {
        const value = process.env[key];
        if (typeof value === 'string') {
          env[key] = value;
        }
      }
      for (const key of shellCfg.envAllowlist || []) {
        const value = process.env[key];
        if (typeof value === 'string') {
          env[key] = value;
        }
      }

      const child = spawn(commandConfig.command, commandConfig.args || [], {
        stdio: ['pipe', 'pipe', 'pipe'],
        env,
      });

      const timer = setTimeout(() => {
        child.kill('SIGTERM');
        reject(new Error(`Shell hook timed out after ${timeoutMs}ms (${commandConfig.command})`));
      }, timeoutMs);

      let stderr = '';
      child.stderr.on('data', (chunk) => {
        stderr += String(chunk);
      });

      child.on('error', (err) => {
        clearTimeout(timer);
        reject(err);
      });

      child.on('exit', (code) => {
        clearTimeout(timer);
        if (code === 0) {
          resolve();
          return;
        }
        reject(
          new Error(
            `Shell hook failed (${commandConfig.command}) exit=${code}${stderr ? `: ${stderr.trim()}` : ''}`,
          ),
        );
      });

      try {
        child.stdin.write(JSON.stringify({ event: commandConfig.event, payload: data }));
      } catch {
        // Non-serializable payloads are best-effort only.
      }
      child.stdin.end();
    });
  }

  /**
   * Register a hook.
   */
  registerHook(hook: Hook): void {
    const existing = this.hooks.get(hook.event) || [];

    // Check for duplicate by ID or handler reference
    if (hook.id && existing.some((h) => h.id === hook.id)) {
      logger.warn('Hook already registered', { hookId: hook.id, event: hook.event });
      return;
    }
    if (existing.some((h) => h.handler === hook.handler)) {
      logger.warn('Duplicate handler already registered', { event: hook.event });
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
        logger.error('Hook execution error', { event, error: String(err) });
      }
    }
  }

  /**
   * Load and initialize a plugin.
   */
  async loadPlugin(plugin: Plugin): Promise<void> {
    if (this.plugins.has(plugin.name)) {
      logger.warn('Plugin already loaded', { plugin: plugin.name });
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
        logger.info('Plugin log', { plugin: plugin.name, level, message });
      },
    };

    try {
      await plugin.initialize(context);
      this.plugins.set(plugin.name, plugin);
      logger.info('Plugin loaded', { plugin: plugin.name, version: plugin.version });
    } catch (err) {
      logger.error('Failed to load plugin', { plugin: plugin.name, error: String(err) });
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
    logger.info('Plugin unloaded', { plugin: name });
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
   * Synchronous listeners are called immediately.
   * Async hooks are fire-and-forget but errors are tracked.
   */
  emit(event: AgentEvent): void {
    // Sync listeners (unchanged)
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch (err) {
        logger.error('Event listener error', { error: String(err) });
      }
    }

    // Map agent events to hook events
    const hookEvent = this.mapToHookEvent(event);
    if (hookEvent) {
      // Fire-and-forget WITH error tracking
      const hookPromise = this.executeHooks(hookEvent, event)
        .catch((err) => this.recordHookError(hookEvent, err))
        .finally(() => this.pendingHooks.delete(hookPromise));
      this.pendingHooks.add(hookPromise);
    }
  }

  /**
   * Emit an event and wait for all hooks to complete.
   * Use this for critical events that MUST complete before continuing.
   */
  async emitAsync(event: AgentEvent): Promise<void> {
    // Sync listeners
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch (err) {
        logger.error('Event listener error', { error: String(err) });
      }
    }

    // Map agent events to hook events and await
    const hookEvent = this.mapToHookEvent(event);
    if (hookEvent) {
      await this.executeHooks(hookEvent, event);
    }
  }

  /**
   * Wait for all pending hooks to complete.
   * Call this before shutdown or when you need to ensure all hooks have finished.
   */
  async flush(): Promise<void> {
    if (this.pendingHooks.size === 0) {
      return;
    }

    // Wait for all pending hooks (they already have error handling)
    await Promise.all(Array.from(this.pendingHooks));
  }

  /**
   * Record a hook error for observability.
   */
  private recordHookError(event: HookEvent, error: unknown): void {
    const hookError: HookError = {
      event,
      error: error instanceof Error ? error : new Error(String(error)),
      timestamp: new Date(),
    };

    // Add to bounded error history
    this.hookErrors.push(hookError);
    if (this.hookErrors.length > this.maxHookErrors) {
      this.hookErrors.shift();
    }

    // Notify error listeners
    for (const listener of this.errorListeners) {
      try {
        listener(hookError);
      } catch {
        // Ignore errors in error listeners to prevent cascading failures
      }
    }

    // Always log for visibility
    logger.error('Hook error', { event, error: hookError.error.message });
  }

  /**
   * Subscribe to hook errors for observability.
   * Returns an unsubscribe function.
   */
  subscribeToErrors(listener: HookErrorListener): () => void {
    this.errorListeners.add(listener);
    return () => this.errorListeners.delete(listener);
  }

  /**
   * Get recent hook errors.
   */
  getHookErrors(limit = 10): HookError[] {
    return this.hookErrors.slice(-limit);
  }

  /**
   * Get count of pending hooks (for diagnostics).
   */
  getPendingHookCount(): number {
    return this.pendingHooks.size;
  }

  /**
   * Map agent event to hook event.
   */
  private mapToHookEvent(event: AgentEvent): HookEvent | null {
    switch (event.type) {
      case 'run.before':
        return 'run.before';
      case 'run.after':
        return 'run.after';
      case 'iteration.before':
        return 'iteration.before';
      case 'iteration.after':
        return 'iteration.after';
      case 'completion.before':
        return 'completion.before';
      case 'completion.after':
        return 'completion.after';
      case 'recovery.before':
        return 'recovery.before';
      case 'recovery.after':
        return 'recovery.after';
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
   * Cleanup all plugins and flush pending hooks.
   */
  async cleanup(): Promise<void> {
    // Wait for pending hooks to complete
    await this.flush();

    // Unload all plugins
    for (const name of this.plugins.keys()) {
      await this.unloadPlugin(name);
    }

    // Clear error listeners
    this.errorListeners.clear();
  }
}

// =============================================================================
// FACTORY
// =============================================================================

export function createHookManager(
  hooksConfig: HooksConfig,
  pluginsConfig: PluginsConfig,
): HookManager {
  return new HookManager(hooksConfig, pluginsConfig);
}
