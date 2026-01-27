/**
 * Exercise Tests: Lesson 11 - Plugin Loader
 */
import { describe, it, expect } from 'vitest';
import { PluginLoader } from './exercises/answers/exercise-1.js';

describe('PluginLoader', () => {
  it('should register plugins', () => {
    const loader = new PluginLoader();
    loader.register({ name: 'test', version: '1.0' });
    expect(loader.get('test')?.state).toBe('registered');
  });

  it('should load plugins', async () => {
    const loader = new PluginLoader();
    loader.register({ name: 'test', version: '1.0' });
    await loader.load('test');
    expect(loader.get('test')?.state).toBe('loaded');
  });

  it('should check dependencies on load', async () => {
    const loader = new PluginLoader();
    loader.register({ name: 'child', version: '1.0', dependencies: ['parent'] });

    await expect(loader.load('child')).rejects.toThrow('Dependency');
  });

  it('should activate plugins with context', async () => {
    const loader = new PluginLoader();
    loader.register({ name: 'test', version: '1.0' });
    await loader.load('test');

    await loader.activate('test', async (ctx) => {
      expect(ctx.pluginName).toBe('test');
      return { initialized: true };
    });

    expect(loader.get('test')?.state).toBe('active');
    expect(loader.get('test')?.instance).toEqual({ initialized: true });
  });

  it('should deactivate plugins', async () => {
    const loader = new PluginLoader();
    loader.register({ name: 'test', version: '1.0' });
    await loader.load('test');
    await loader.activate('test', async () => ({}));
    await loader.deactivate('test');

    expect(loader.get('test')?.state).toBe('loaded');
  });

  it('should return all plugins', () => {
    const loader = new PluginLoader();
    loader.register({ name: 'a', version: '1.0' });
    loader.register({ name: 'b', version: '1.0' });
    expect(loader.getAll()).toHaveLength(2);
  });
});
