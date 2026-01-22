/**
 * Hierarchical Configuration Tests
 *
 * Tests for the hierarchical configuration system that manages cascading config levels.
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { mkdir, writeFile, rm } from 'fs/promises';
import { join } from 'path';
import { tmpdir } from 'os';
import {
  HierarchicalConfigManager,
  createHierarchicalConfig,
  createAndLoadConfig,
  getSampleGlobalConfig,
  getSampleWorkspaceConfig,
  type ConfigLevel,
} from '../src/integrations/hierarchical-config.js';

// Test config type
interface TestConfig {
  name: string;
  count: number;
  nested?: { value: string };
  enabled?: boolean;
}

describe('HierarchicalConfigManager', () => {
  let manager: HierarchicalConfigManager<TestConfig>;
  let testDir: string;

  beforeEach(async () => {
    testDir = join(tmpdir(), `config-test-${Date.now()}`);
    await mkdir(testDir, { recursive: true });

    // Create with autoLoad disabled to control loading in tests
    manager = new HierarchicalConfigManager<TestConfig>(
      { name: 'default', count: 0 },
      { autoLoad: false, workspaceDir: testDir }
    );
  });

  afterEach(async () => {
    manager.cleanup();
    await rm(testDir, { recursive: true, force: true });
  });

  describe('initialization', () => {
    it('should create manager with default values', () => {
      const config = manager.getConfig();
      expect(config.name).toBe('default');
      expect(config.count).toBe(0);
    });

    it('should create manager without defaults', () => {
      const emptyManager = new HierarchicalConfigManager<TestConfig>(undefined, {
        autoLoad: false,
      });
      const config = emptyManager.getConfig();
      expect(config).toEqual({});
      emptyManager.cleanup();
    });
  });

  describe('level management', () => {
    it('should set and get levels', () => {
      manager.setLevel('global', { name: 'global-name' }, 'test');

      const level = manager.getLevel('global');
      expect(level).toBeDefined();
      expect(level?.values.name).toBe('global-name');
      expect(level?.source).toBe('test');
    });

    it('should update levels', () => {
      manager.setLevel('global', { name: 'initial' });
      manager.updateLevel('global', { count: 5 });

      const level = manager.getLevel('global');
      expect(level?.values.name).toBe('initial');
      expect(level?.values.count).toBe(5);
    });

    it('should return undefined for unset levels', () => {
      expect(manager.getLevel('global')).toBeUndefined();
    });
  });

  describe('session overrides', () => {
    it('should set session overrides', () => {
      manager.setSessionOverride('name', 'session-override');

      const config = manager.getConfig();
      expect(config.name).toBe('session-override');
    });

    it('should clear specific session overrides', () => {
      manager.setSessionOverride('name', 'override');
      manager.clearSessionOverride('name');

      const config = manager.getConfig();
      expect(config.name).toBe('default'); // Back to default
    });

    it('should clear all session overrides', () => {
      manager.setSessionOverride('name', 'override1');
      manager.setSessionOverride('count', 999);
      manager.clearSessionOverrides();

      const config = manager.getConfig();
      expect(config.name).toBe('default');
      expect(config.count).toBe(0);
    });
  });

  describe('resolution', () => {
    it('should resolve configuration by priority', () => {
      manager.setLevel('global', { name: 'global', count: 10 });
      manager.setLevel('workspace', { name: 'workspace' });
      manager.setSessionOverride('count', 100);

      const config = manager.getConfig();
      expect(config.name).toBe('workspace'); // workspace > global
      expect(config.count).toBe(100); // session > workspace
    });

    it('should track value sources', () => {
      manager.setLevel('global', { name: 'global' });
      manager.setSessionOverride('count', 50);

      expect(manager.getSource('name')).toBe('global');
      expect(manager.getSource('count')).toBe('session');
    });

    it('should get values with defaults', () => {
      expect(manager.getWithDefault('enabled', true)).toBe(true);

      manager.setLevel('global', { enabled: false } as Partial<TestConfig>);
      expect(manager.getWithDefault('enabled', true)).toBe(false);
    });

    it('should cache resolved config', () => {
      const resolved1 = manager.resolve();
      const resolved2 = manager.resolve();

      expect(resolved1).toBe(resolved2); // Same object reference
    });

    it('should invalidate cache on changes', () => {
      const resolved1 = manager.resolve();
      manager.setLevel('global', { name: 'changed' });
      const resolved2 = manager.resolve();

      expect(resolved1).not.toBe(resolved2);
    });
  });

  describe('file loading', () => {
    it('should load from file', async () => {
      const configPath = join(testDir, 'config.json');
      await writeFile(configPath, JSON.stringify({ name: 'from-file', count: 42 }));

      const loaded = manager.loadFromFile(configPath, 'global');

      expect(loaded).toBe(true);
      expect(manager.get('name')).toBe('from-file');
      expect(manager.get('count')).toBe(42);
    });

    it('should return false for missing files', () => {
      const loaded = manager.loadFromFile('/nonexistent/path.json', 'global');
      expect(loaded).toBe(false);
    });

    it('should emit error for invalid JSON', async () => {
      const configPath = join(testDir, 'invalid.json');
      await writeFile(configPath, '{ invalid json }');

      const events: unknown[] = [];
      manager.subscribe((e) => events.push(e));

      const loaded = manager.loadFromFile(configPath, 'global');

      expect(loaded).toBe(false);
      expect(events.some((e: any) => e.type === 'config.error')).toBe(true);
    });

    it('should load workspace config', async () => {
      const agentDir = join(testDir, '.agent');
      await mkdir(agentDir, { recursive: true });
      await writeFile(
        join(agentDir, 'config.json'),
        JSON.stringify({ name: 'workspace-config' })
      );

      const loaded = manager.loadWorkspace();

      expect(loaded).toBe(true);
      expect(manager.get('name')).toBe('workspace-config');
    });

    it('should save to file', async () => {
      manager.setLevel('workspace', { name: 'to-save', count: 123 });

      const savePath = join(testDir, 'saved.json');
      const saved = manager.saveToFile(savePath, 'workspace');

      expect(saved).toBe(true);

      // Verify by loading
      const newManager = new HierarchicalConfigManager<TestConfig>(undefined, {
        autoLoad: false,
      });
      newManager.loadFromFile(savePath, 'global');
      expect(newManager.get('name')).toBe('to-save');
      newManager.cleanup();
    });

    it('should create directories when saving', async () => {
      manager.setLevel('workspace', { name: 'test' });

      const deepPath = join(testDir, 'deep', 'nested', 'config.json');
      const saved = manager.saveToFile(deepPath, 'workspace');

      expect(saved).toBe(true);
    });

    it('should reload configurations', async () => {
      const agentDir = join(testDir, '.agent');
      await mkdir(agentDir, { recursive: true });
      await writeFile(join(agentDir, 'config.json'), JSON.stringify({ name: 'initial' }));

      manager.loadWorkspace();
      expect(manager.get('name')).toBe('initial');

      // Modify file
      await writeFile(join(agentDir, 'config.json'), JSON.stringify({ name: 'reloaded' }));

      manager.reload();
      expect(manager.get('name')).toBe('reloaded');
    });

    it('should preserve session overrides on reload', async () => {
      manager.setSessionOverride('count', 999);

      manager.reload();

      expect(manager.get('count')).toBe(999);
    });
  });

  describe('events', () => {
    it('should emit config.loaded event', () => {
      const events: unknown[] = [];
      manager.subscribe((e) => events.push(e));

      manager.setLevel('global', { name: 'test' }, 'test-source');

      const loadEvents = events.filter((e: any) => e.type === 'config.loaded');
      expect(loadEvents.length).toBe(1);
      expect((loadEvents[0] as any).level).toBe('global');
      expect((loadEvents[0] as any).source).toBe('test-source');
    });

    it('should emit config.changed event', () => {
      manager.setLevel('global', { name: 'old' });

      const events: unknown[] = [];
      manager.subscribe((e) => events.push(e));

      manager.setLevel('global', { name: 'new' });

      const changeEvents = events.filter((e: any) => e.type === 'config.changed');
      expect(changeEvents.length).toBe(1);
      expect((changeEvents[0] as any).key).toBe('name');
      expect((changeEvents[0] as any).oldValue).toBe('old');
      expect((changeEvents[0] as any).newValue).toBe('new');
    });

    it('should emit config.resolved event', () => {
      const events: unknown[] = [];
      manager.subscribe((e) => events.push(e));

      manager.resolve();

      const resolveEvents = events.filter((e: any) => e.type === 'config.resolved');
      expect(resolveEvents.length).toBe(1);
    });

    it('should allow unsubscribe', () => {
      const events: unknown[] = [];
      const unsubscribe = manager.subscribe((e) => events.push(e));

      manager.setLevel('global', { name: 'first' });
      unsubscribe();
      manager.setLevel('global', { name: 'second' });

      // Only first event captured
      const loadEvents = events.filter((e: any) => e.type === 'config.loaded');
      expect(loadEvents.length).toBe(1);
    });
  });

  describe('utilities', () => {
    it('should diff between levels', () => {
      manager.setLevel('global', { name: 'global', count: 1 });
      manager.setLevel('workspace', { name: 'workspace', enabled: true } as Partial<TestConfig>);

      const diff = manager.diff('global', 'workspace');

      expect(diff.added).toContain('enabled'); // In workspace, not global
      expect(diff.removed).toContain('count'); // In global, not workspace
      expect(diff.changed).toContain('name'); // Different values
    });

    it('should export resolved configuration', () => {
      manager.setLevel('global', { name: 'exported', count: 5 });

      const exported = manager.exportResolved();
      const parsed = JSON.parse(exported);

      expect(parsed.name).toBe('exported');
      expect(parsed.count).toBe(5);
    });

    it('should get loaded levels info', () => {
      manager.setLevel('global', { name: 'g' }, 'global-source');
      manager.setLevel('workspace', { name: 'w' }, 'workspace-source');

      const levels = manager.getLoadedLevels();

      expect(levels.length).toBe(3); // default + global + workspace
      expect(levels.some((l) => l.level === 'global' && l.source === 'global-source')).toBe(true);
    });

    it('should reset to defaults', () => {
      manager.setLevel('global', { name: 'global' });
      manager.setLevel('workspace', { name: 'workspace' });

      manager.reset();

      expect(manager.get('name')).toBe('default');
      expect(manager.getLevel('global')).toBeUndefined();
      expect(manager.getLevel('workspace')).toBeUndefined();
    });
  });
});

describe('createHierarchicalConfig', () => {
  it('should create manager with factory function', () => {
    const manager = createHierarchicalConfig<TestConfig>(
      { name: 'test', count: 0 },
      { autoLoad: false }
    );

    expect(manager.get('name')).toBe('test');
    manager.cleanup();
  });
});

describe('createAndLoadConfig', () => {
  it('should create and auto-load config', () => {
    const manager = createAndLoadConfig<TestConfig>(
      { name: 'default', count: 0 },
      '/tmp'
    );

    // Should have defaults loaded
    expect(manager.get('name')).toBe('default');
    manager.cleanup();
  });
});

describe('Sample config functions', () => {
  describe('getSampleGlobalConfig', () => {
    it('should return valid global config sample', () => {
      const config = getSampleGlobalConfig();

      expect(config.model).toBeDefined();
      expect(config.maxIterations).toBeDefined();
      expect(config.timeout).toBeDefined();
      expect(config.memory).toBeDefined();
      expect(config.sandbox).toBeDefined();
    });
  });

  describe('getSampleWorkspaceConfig', () => {
    it('should return valid workspace config sample', () => {
      const config = getSampleWorkspaceConfig();

      expect(config.systemPrompt).toBeDefined();
      expect(config.sandbox).toBeDefined();
      expect(config.rules).toBeDefined();
    });
  });
});

describe('Configuration priority', () => {
  let manager: HierarchicalConfigManager<TestConfig>;

  beforeEach(() => {
    manager = new HierarchicalConfigManager<TestConfig>(
      { name: 'default', count: 0 },
      { autoLoad: false }
    );
  });

  afterEach(() => {
    manager.cleanup();
  });

  it('should respect priority: default < global < workspace < session < override', () => {
    // Set at all levels
    manager.setLevel('default', { name: 'default' });
    manager.setLevel('global', { name: 'global' });
    manager.setLevel('workspace', { name: 'workspace' });
    manager.setSessionOverride('name', 'session');
    manager.setLevel('override', { name: 'override' });

    // Override should win
    expect(manager.get('name')).toBe('override');

    // Remove override - session should win
    manager.setLevel('override', {});
    expect(manager.get('name')).toBe('session');

    // Clear session - workspace should win
    manager.clearSessionOverride('name');
    expect(manager.get('name')).toBe('workspace');
  });

  it('should merge across levels correctly', () => {
    manager.setLevel('default', { name: 'default', count: 1 });
    manager.setLevel('global', { count: 10 }); // Only override count
    manager.setLevel('workspace', { enabled: true } as Partial<TestConfig>); // Add new key

    const config = manager.getConfig();
    expect(config.name).toBe('default'); // From default
    expect(config.count).toBe(10); // From global
    expect(config.enabled).toBe(true); // From workspace
  });
});
