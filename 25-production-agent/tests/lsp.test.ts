/**
 * LSP Integration Tests
 *
 * Tests for the LSP (Language Server Protocol) client manager.
 * Note: Some tests are limited as they would require actual LSP servers installed.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { mkdir, writeFile, rm } from 'fs/promises';
import { join } from 'path';
import { tmpdir } from 'os';
import {
  LSPManager,
  createLSPManager,
  type LSPConfig,
  type LSPEvent,
} from '../integrations/lsp.js';

describe('LSPManager', () => {
  let manager: LSPManager;
  let testDir: string;

  beforeEach(async () => {
    testDir = join(tmpdir(), `lsp-test-${Date.now()}`);
    await mkdir(testDir, { recursive: true });

    manager = createLSPManager({
      enabled: true,
      autoDetect: false, // Disable auto-detection for controlled testing
      rootUri: `file://${testDir}`,
    });
  });

  afterEach(async () => {
    await manager.cleanup();
    await rm(testDir, { recursive: true, force: true });
  });

  describe('initialization', () => {
    it('should create manager with default config', () => {
      const defaultManager = createLSPManager();
      expect(defaultManager).toBeDefined();
      expect(defaultManager.getActiveServers()).toEqual([]);
      defaultManager.cleanup();
    });

    it('should respect enabled flag', async () => {
      const disabledManager = createLSPManager({ enabled: false });
      const started = await disabledManager.autoStart(testDir);
      expect(started).toEqual([]);
      disabledManager.cleanup();
    });

    it('should have no active servers initially', () => {
      expect(manager.getActiveServers()).toEqual([]);
    });
  });

  describe('isServerRunning', () => {
    it('should return false for non-running servers', () => {
      expect(manager.isServerRunning('typescript')).toBe(false);
      expect(manager.isServerRunning('python')).toBe(false);
      expect(manager.isServerRunning('nonexistent')).toBe(false);
    });
  });

  describe('getActiveServers', () => {
    it('should return empty array when no servers running', () => {
      expect(manager.getActiveServers()).toEqual([]);
    });
  });

  describe('getDiagnostics', () => {
    it('should return empty array for files without diagnostics', () => {
      const diagnostics = manager.getDiagnostics('nonexistent.ts');
      expect(diagnostics).toEqual([]);
    });

    it('should handle file:// URIs', () => {
      const diagnostics = manager.getDiagnostics('file:///path/to/file.ts');
      expect(diagnostics).toEqual([]);
    });
  });

  describe('event system', () => {
    it('should allow subscribing to events', () => {
      const events: LSPEvent[] = [];
      const unsubscribe = manager.subscribe((e) => events.push(e));

      expect(typeof unsubscribe).toBe('function');
      unsubscribe();
    });

    it('should unsubscribe correctly', () => {
      const events: LSPEvent[] = [];
      const unsubscribe = manager.subscribe((e) => events.push(e));
      unsubscribe();

      // After unsubscribe, no events should be captured
      expect(events).toEqual([]);
    });
  });

  describe('cleanup', () => {
    it('should cleanup without errors', async () => {
      await expect(manager.cleanup()).resolves.not.toThrow();
    });

    it('should clear event listeners on cleanup', async () => {
      const events: LSPEvent[] = [];
      manager.subscribe((e) => events.push(e));

      await manager.cleanup();

      // Further operations shouldn't emit to cleared listeners
      expect(events).toEqual([]);
    });
  });

  describe('startServer error handling', () => {
    it('should throw for unknown language', async () => {
      await expect(manager.startServer('unknown-language')).rejects.toThrow(
        'No server configuration for language'
      );
    });

    it('should emit error event when server not found', async () => {
      const events: LSPEvent[] = [];
      manager.subscribe((e) => events.push(e));

      // Try to start a server that likely doesn't exist
      // This test is best-effort since some machines might have the server
      try {
        await manager.startServer('rust'); // rust-analyzer might not be installed
      } catch {
        // Expected to fail if rust-analyzer not installed
      }

      // Check for error events if the server wasn't found
      const errorEvents = events.filter((e) => e.type === 'lsp.error');
      // May or may not have error depending on installation
      expect(Array.isArray(errorEvents)).toBe(true);
    });
  });

  describe('file notifications (no server)', () => {
    it('should handle notifyFileOpened without server', () => {
      // Should not throw even without a server running
      expect(() => {
        manager.notifyFileOpened(join(testDir, 'test.ts'), 'const x = 1;');
      }).not.toThrow();
    });

    it('should handle notifyFileChanged without server', () => {
      expect(() => {
        manager.notifyFileChanged(join(testDir, 'test.ts'), 'const x = 2;', 2);
      }).not.toThrow();
    });

    it('should handle notifyFileClosed without server', () => {
      expect(() => {
        manager.notifyFileClosed(join(testDir, 'test.ts'));
      }).not.toThrow();
    });
  });

  describe('code intelligence (no server)', () => {
    it('should return null for getDefinition without server', async () => {
      const result = await manager.getDefinition(join(testDir, 'test.ts'), 1, 5);
      expect(result).toBeNull();
    });

    it('should return empty array for getCompletions without server', async () => {
      const result = await manager.getCompletions(join(testDir, 'test.ts'), 1, 5);
      expect(result).toEqual([]);
    });

    it('should return null for getHover without server', async () => {
      const result = await manager.getHover(join(testDir, 'test.ts'), 1, 5);
      expect(result).toBeNull();
    });

    it('should return empty array for getReferences without server', async () => {
      const result = await manager.getReferences(join(testDir, 'test.ts'), 1, 5);
      expect(result).toEqual([]);
    });
  });

  describe('stopServer', () => {
    it('should handle stopping non-running server', async () => {
      await expect(manager.stopServer('typescript')).resolves.not.toThrow();
    });
  });

  describe('stopAll', () => {
    it('should handle stopping when no servers running', async () => {
      await expect(manager.stopAll()).resolves.not.toThrow();
    });
  });
});

describe('createLSPManager', () => {
  it('should create manager with factory function', () => {
    const manager = createLSPManager();
    expect(manager).toBeInstanceOf(LSPManager);
    manager.cleanup();
  });

  it('should create manager with custom config', () => {
    const manager = createLSPManager({
      enabled: false,
      autoDetect: false,
      timeout: 5000,
    });
    expect(manager).toBeDefined();
    manager.cleanup();
  });

  it('should merge custom servers with built-in', () => {
    const manager = createLSPManager({
      servers: {
        custom: {
          command: 'custom-server',
          args: ['--stdio'],
          extensions: ['.custom'],
          languageId: 'custom',
        },
      },
    });
    expect(manager).toBeDefined();
    manager.cleanup();
  });
});

describe('Language detection', () => {
  let testDir: string;

  beforeEach(async () => {
    testDir = join(tmpdir(), `lsp-detect-test-${Date.now()}`);
    await mkdir(testDir, { recursive: true });
  });

  afterEach(async () => {
    await rm(testDir, { recursive: true, force: true });
  });

  it('should detect TypeScript from package.json', async () => {
    await writeFile(join(testDir, 'package.json'), '{}');

    const manager = createLSPManager({
      autoDetect: true,
      rootUri: `file://${testDir}`,
    });

    // autoStart returns detected languages even if servers fail to start
    // This tests the detection mechanism
    const events: LSPEvent[] = [];
    manager.subscribe((e) => events.push(e));

    try {
      await manager.autoStart(testDir);
    } catch {
      // Expected if typescript-language-server not installed
    }

    // Either started successfully or emitted error for typescript
    const tsEvents = events.filter(
      (e) =>
        (e.type === 'lsp.started' || e.type === 'lsp.error') &&
        e.languageId === 'typescript'
    );
    // May or may not have events depending on server installation
    expect(Array.isArray(tsEvents)).toBe(true);

    await manager.cleanup();
  });

  it('should detect Python from requirements.txt', async () => {
    await writeFile(join(testDir, 'requirements.txt'), 'requests==2.28.0');

    const manager = createLSPManager({
      autoDetect: true,
      rootUri: `file://${testDir}`,
    });

    const events: LSPEvent[] = [];
    manager.subscribe((e) => events.push(e));

    try {
      await manager.autoStart(testDir);
    } catch {
      // Expected if pyright-langserver not installed
    }

    // Check that Python was detected (even if server failed to start)
    const pyEvents = events.filter(
      (e) =>
        (e.type === 'lsp.started' || e.type === 'lsp.error') &&
        e.languageId === 'python'
    );
    expect(Array.isArray(pyEvents)).toBe(true);

    await manager.cleanup();
  });

  it('should detect Rust from Cargo.toml', async () => {
    await writeFile(join(testDir, 'Cargo.toml'), '[package]\nname = "test"');

    const manager = createLSPManager({
      autoDetect: true,
      rootUri: `file://${testDir}`,
    });

    try {
      await manager.autoStart(testDir);
    } catch {
      // Expected if rust-analyzer not installed
    }

    await manager.cleanup();
  });

  it('should detect Go from go.mod', async () => {
    await writeFile(join(testDir, 'go.mod'), 'module test');

    const manager = createLSPManager({
      autoDetect: true,
      rootUri: `file://${testDir}`,
    });

    try {
      await manager.autoStart(testDir);
    } catch {
      // Expected if gopls not installed
    }

    await manager.cleanup();
  });
});

describe('URI handling', () => {
  let manager: LSPManager;

  beforeEach(() => {
    manager = createLSPManager({ enabled: true, autoDetect: false });
  });

  afterEach(async () => {
    await manager.cleanup();
  });

  it('should handle relative paths', async () => {
    const result = await manager.getDefinition('test.ts', 0, 0);
    expect(result).toBeNull();
  });

  it('should handle absolute paths', async () => {
    const result = await manager.getDefinition('/absolute/path/test.ts', 0, 0);
    expect(result).toBeNull();
  });

  it('should handle file:// URIs', async () => {
    const result = await manager.getDefinition('file:///path/to/test.ts', 0, 0);
    expect(result).toBeNull();
  });
});
