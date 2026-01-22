/**
 * Ignore Manager Tests
 *
 * Tests for the .agentignore system that filters files from the agent.
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { mkdir, writeFile, rm } from 'fs/promises';
import { join } from 'path';
import { tmpdir } from 'os';
import {
  IgnoreManager,
  createIgnoreManager,
  quickShouldIgnore,
  getSampleAgentignore,
  getBuiltinIgnorePatterns,
} from '../src/integrations/ignore.js';

describe('IgnoreManager', () => {
  let manager: IgnoreManager;
  let testDir: string;

  beforeEach(async () => {
    testDir = join(tmpdir(), `ignore-test-${Date.now()}`);
    await mkdir(testDir, { recursive: true });

    manager = createIgnoreManager({
      enabled: true,
      includeGitignore: false,
      includeGlobal: false,
      extraPatterns: [],
    });
  });

  afterEach(async () => {
    manager.cleanup();
    await rm(testDir, { recursive: true, force: true });
  });

  describe('initialization', () => {
    it('should create manager with default config', () => {
      const defaultManager = createIgnoreManager();
      expect(defaultManager).toBeDefined();
      defaultManager.cleanup();
    });

    it('should include built-in patterns by default', () => {
      const patterns = manager.getPatterns();
      expect(patterns.length).toBeGreaterThan(0);
    });

    it('should respect enabled flag', () => {
      const disabled = createIgnoreManager({ enabled: false });
      expect(disabled.shouldIgnore('node_modules')).toBe(false);
      disabled.cleanup();
    });
  });

  describe('built-in patterns', () => {
    it('should ignore node_modules', () => {
      expect(manager.shouldIgnore('node_modules')).toBe(true);
      expect(manager.shouldIgnore('src/node_modules')).toBe(true);
    });

    it('should ignore .git', () => {
      expect(manager.shouldIgnore('.git')).toBe(true);
      expect(manager.shouldIgnore('.git/config')).toBe(true);
    });

    it('should ignore .env files', () => {
      expect(manager.shouldIgnore('.env')).toBe(true);
      expect(manager.shouldIgnore('.env.local')).toBe(true);
    });

    it('should ignore IDE directories', () => {
      expect(manager.shouldIgnore('.idea')).toBe(true);
      expect(manager.shouldIgnore('.vscode')).toBe(true);
    });

    it('should ignore OS files', () => {
      expect(manager.shouldIgnore('.DS_Store')).toBe(true);
      expect(manager.shouldIgnore('Thumbs.db')).toBe(true);
    });
  });

  describe('load', () => {
    it('should load patterns from .agentignore', async () => {
      await writeFile(
        join(testDir, '.agentignore'),
        `# Custom ignore file
*.log
temp/
secret.txt
`
      );

      await manager.load(testDir);

      expect(manager.shouldIgnore('app.log')).toBe(true);
      expect(manager.shouldIgnore('temp/')).toBe(true);
      expect(manager.shouldIgnore('secret.txt')).toBe(true);
    });

    it('should load patterns from .gitignore when enabled', async () => {
      const gitManager = createIgnoreManager({
        includeGitignore: true,
        includeGlobal: false,
      });

      await writeFile(
        join(testDir, '.gitignore'),
        `dist/
*.min.js
`
      );

      await gitManager.load(testDir);

      expect(gitManager.shouldIgnore('dist/')).toBe(true);
      expect(gitManager.shouldIgnore('bundle.min.js')).toBe(true);

      gitManager.cleanup();
    });

    it('should handle missing ignore files gracefully', async () => {
      await manager.load(testDir);
      expect(manager.isLoaded()).toBe(true);
    });
  });

  describe('pattern matching', () => {
    it('should match exact filenames', async () => {
      manager.addPatterns(['secret.txt']);
      expect(manager.shouldIgnore('secret.txt')).toBe(true);
      expect(manager.shouldIgnore('other.txt')).toBe(false);
    });

    it('should match glob patterns with *', async () => {
      manager.addPatterns(['*.log']);
      expect(manager.shouldIgnore('app.log')).toBe(true);
      expect(manager.shouldIgnore('error.log')).toBe(true);
      expect(manager.shouldIgnore('log.txt')).toBe(false);
    });

    it('should match directory patterns ending with /', async () => {
      manager.addPatterns(['build/']);
      expect(manager.shouldIgnore('build/', true)).toBe(true);
      expect(manager.shouldIgnore('build', true)).toBe(true);
    });

    it('should handle ** for recursive matching', async () => {
      manager.addPatterns(['**/test/**']);
      expect(manager.shouldIgnore('src/test/file.ts')).toBe(true);
      expect(manager.shouldIgnore('test/unit/spec.ts')).toBe(true);
    });

    it('should handle negation patterns with !', async () => {
      manager.addPatterns(['*.log', '!important.log']);

      expect(manager.shouldIgnore('debug.log')).toBe(true);
      expect(manager.shouldIgnore('important.log')).toBe(false);
    });

    it('should handle patterns starting with /', async () => {
      manager.addPatterns(['/root-only.txt']);

      expect(manager.shouldIgnore('root-only.txt')).toBe(true);
      // Pattern anchored to root shouldn't match in subdirs
      // (behavior may vary based on implementation)
    });

    it('should match paths with directories', async () => {
      manager.addPatterns(['logs/*.log']);

      expect(manager.shouldIgnore('logs/app.log')).toBe(true);
    });
  });

  describe('addPatterns', () => {
    it('should add patterns dynamically', () => {
      const initialCount = manager.getPatterns().length;

      manager.addPatterns(['new-pattern', 'another-pattern']);

      expect(manager.getPatterns().length).toBe(initialCount + 2);
    });

    it('should ignore comments and empty lines', () => {
      const initialCount = manager.getPatterns().length;

      manager.addPatterns(['# comment', '', '  ', 'valid-pattern']);

      expect(manager.getPatterns().length).toBe(initialCount + 1);
    });
  });

  describe('filterPaths', () => {
    it('should filter ignored paths from list', () => {
      manager.addPatterns(['*.log', 'temp/']);

      const paths = ['src/app.ts', 'debug.log', 'temp/cache', 'README.md'];
      const filtered = manager.filterPaths(paths);

      expect(filtered).toContain('src/app.ts');
      expect(filtered).toContain('README.md');
      expect(filtered).not.toContain('debug.log');
      expect(filtered).not.toContain('temp/cache');
    });

    it('should return all paths when disabled', () => {
      const disabled = createIgnoreManager({ enabled: false });
      const paths = ['node_modules/package', '.env'];

      const filtered = disabled.filterPaths(paths);

      expect(filtered).toEqual(paths);
      disabled.cleanup();
    });
  });

  describe('clear and reload', () => {
    it('should clear all patterns', async () => {
      manager.addPatterns(['pattern1', 'pattern2']);
      manager.clear();

      expect(manager.getPatterns().length).toBe(0);
      expect(manager.isLoaded()).toBe(false);
    });

    it('should reload patterns from files', async () => {
      await writeFile(join(testDir, '.agentignore'), 'reloaded.txt');

      await manager.load(testDir);
      expect(manager.shouldIgnore('reloaded.txt')).toBe(true);

      // Modify file
      await writeFile(join(testDir, '.agentignore'), 'different.txt');

      await manager.reload();
      expect(manager.shouldIgnore('different.txt')).toBe(true);
    });
  });

  describe('events', () => {
    it('should emit events when loading files', async () => {
      const events: unknown[] = [];
      manager.subscribe(e => events.push(e));

      await writeFile(join(testDir, '.agentignore'), '*.test');
      await manager.load(testDir);

      const loadEvents = events.filter((e: any) => e.type === 'ignore.loaded');
      expect(loadEvents.length).toBeGreaterThan(0);
    });

    it('should emit events when matching paths', async () => {
      const events: unknown[] = [];
      manager.subscribe(e => events.push(e));

      manager.addPatterns(['track-me']);
      manager.shouldIgnore('track-me');

      const matchEvents = events.filter((e: any) => e.type === 'ignore.matched');
      expect(matchEvents.length).toBe(1);
    });
  });

  describe('extraPatterns config', () => {
    it('should include extra patterns from config', () => {
      const withExtra = createIgnoreManager({
        extraPatterns: ['custom-ignore', 'another-ignore'],
      });

      expect(withExtra.shouldIgnore('custom-ignore')).toBe(true);
      expect(withExtra.shouldIgnore('another-ignore')).toBe(true);

      withExtra.cleanup();
    });
  });
});

describe('quickShouldIgnore', () => {
  it('should check against built-in patterns', () => {
    expect(quickShouldIgnore('node_modules')).toBe(true);
    expect(quickShouldIgnore('.git')).toBe(true);
    expect(quickShouldIgnore('src/app.ts')).toBe(false);
  });
});

describe('getSampleAgentignore', () => {
  it('should return valid ignore file content', () => {
    const content = getSampleAgentignore();

    expect(content).toContain('#');
    expect(content).toContain('.agentignore');
    expect(content.length).toBeGreaterThan(100);
  });
});

describe('getBuiltinIgnorePatterns', () => {
  it('should return list of built-in patterns', () => {
    const patterns = getBuiltinIgnorePatterns();

    expect(Array.isArray(patterns)).toBe(true);
    expect(patterns.length).toBeGreaterThan(0);
    expect(patterns).toContain('node_modules');
    expect(patterns).toContain('.git');
  });
});
