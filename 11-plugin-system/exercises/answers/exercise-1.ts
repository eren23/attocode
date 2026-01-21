/**
 * Exercise 11: Plugin Loader - REFERENCE SOLUTION
 */

export interface PluginConfig {
  name: string;
  version: string;
  dependencies?: string[];
}

export type PluginState = 'registered' | 'loaded' | 'active' | 'error';

export interface Plugin {
  config: PluginConfig;
  state: PluginState;
  instance?: unknown;
  error?: Error;
}

export interface PluginContext {
  pluginName: string;
  registerHook: (name: string, handler: () => void) => void;
  getService: (name: string) => unknown;
}

export class PluginLoader {
  private plugins: Map<string, Plugin> = new Map();
  private hooks: Map<string, Array<() => void>> = new Map();

  register(config: PluginConfig): void {
    this.plugins.set(config.name, {
      config,
      state: 'registered',
    });
  }

  async load(name: string): Promise<void> {
    const plugin = this.plugins.get(name);
    if (!plugin) throw new Error(`Plugin not found: ${name}`);

    // Check dependencies
    for (const dep of plugin.config.dependencies || []) {
      const depPlugin = this.plugins.get(dep);
      if (!depPlugin || depPlugin.state === 'registered') {
        throw new Error(`Dependency not loaded: ${dep}`);
      }
    }

    plugin.state = 'loaded';
  }

  async activate(name: string, initializer: (ctx: PluginContext) => Promise<unknown>): Promise<void> {
    const plugin = this.plugins.get(name);
    if (!plugin) throw new Error(`Plugin not found: ${name}`);
    if (plugin.state !== 'loaded') throw new Error(`Plugin not loaded: ${name}`);

    const context: PluginContext = {
      pluginName: name,
      registerHook: (hookName, handler) => {
        if (!this.hooks.has(hookName)) this.hooks.set(hookName, []);
        this.hooks.get(hookName)!.push(handler);
      },
      getService: (_serviceName) => undefined,
    };

    try {
      plugin.instance = await initializer(context);
      plugin.state = 'active';
    } catch (error) {
      plugin.state = 'error';
      plugin.error = error as Error;
      throw error;
    }
  }

  async deactivate(name: string): Promise<void> {
    const plugin = this.plugins.get(name);
    if (!plugin) throw new Error(`Plugin not found: ${name}`);
    plugin.state = 'loaded';
    plugin.instance = undefined;
  }

  get(name: string): Plugin | undefined {
    return this.plugins.get(name);
  }

  getAll(): Plugin[] {
    return Array.from(this.plugins.values());
  }
}
