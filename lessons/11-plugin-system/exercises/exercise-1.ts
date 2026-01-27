/**
 * Exercise 11: Plugin Loader
 * Implement a plugin system with lifecycle management.
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

/**
 * TODO: Implement PluginLoader
 *
 * 1. register(config): Register a plugin configuration
 * 2. load(name): Load plugin (check dependencies)
 * 3. activate(name, initializer): Initialize with context
 * 4. deactivate(name): Deactivate plugin
 * 5. get(name): Get plugin by name
 */
export class PluginLoader {
  // TODO: private plugins: Map<string, Plugin> = new Map();

  register(_config: PluginConfig): void {
    throw new Error('TODO: Implement register');
  }

  async load(_name: string): Promise<void> {
    // TODO: Check dependencies are loaded first
    throw new Error('TODO: Implement load');
  }

  async activate(_name: string, _initializer: (ctx: PluginContext) => Promise<unknown>): Promise<void> {
    throw new Error('TODO: Implement activate');
  }

  async deactivate(_name: string): Promise<void> {
    throw new Error('TODO: Implement deactivate');
  }

  get(_name: string): Plugin | undefined {
    throw new Error('TODO: Implement get');
  }

  getAll(): Plugin[] {
    throw new Error('TODO: Implement getAll');
  }
}
