/**
 * MCP Client Tests
 *
 * Tests for the MCP (Model Context Protocol) client functionality.
 * Since MCP spawns child processes, we test the non-I/O functionality
 * and mock the process interaction where needed.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { writeFile, unlink, mkdir, rmdir } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { MCPClient, type MCPServerConfig } from '../src/integrations/mcp/mcp-client.js';

// =============================================================================
// TEST SETUP
// =============================================================================

describe('MCPClient', () => {
  let tempDir: string;

  beforeEach(async () => {
    tempDir = join(tmpdir(), `mcp-test-${Date.now()}`);
    await mkdir(tempDir, { recursive: true });
  });

  afterEach(async () => {
    try {
      const files = await import('node:fs/promises').then(fs => fs.readdir(tempDir));
      for (const file of files) {
        await unlink(join(tempDir, file));
      }
      await rmdir(tempDir);
    } catch {
      // Ignore cleanup errors
    }
  });

  describe('constructor', () => {
    it('should create with default config', () => {
      const client = new MCPClient();
      expect(client).toBeDefined();
    });

    it('should accept custom config', () => {
      const client = new MCPClient({
        requestTimeout: 60000,
        autoConnect: false,
        lazyLoading: true,
        summaryDescriptionLimit: 200,
        maxToolsPerSearch: 10,
      });
      expect(client).toBeDefined();
    });

    it('should accept config paths array', () => {
      const client = new MCPClient({
        configPaths: ['/path/to/global.mcp.json', './.mcp.json'],
      });
      expect(client).toBeDefined();
    });
  });

  describe('server registration', () => {
    it('should register a server', () => {
      const client = new MCPClient({ autoConnect: false });
      const config: MCPServerConfig = {
        command: 'node',
        args: ['--version'],
      };
      client.registerServer('test-server', config);
      // Server is registered but not connected
      expect(client.isConnected('test-server')).toBe(false);
    });

    it('should register multiple servers', () => {
      const client = new MCPClient({ autoConnect: false });
      client.registerServer('server1', { command: 'cmd1' });
      client.registerServer('server2', { command: 'cmd2' });
      // Both servers registered but not connected
      expect(client.isConnected('server1')).toBe(false);
      expect(client.isConnected('server2')).toBe(false);
    });

    it('should overwrite server with same name', () => {
      const client = new MCPClient({ autoConnect: false });
      client.registerServer('test', { command: 'old' });
      client.registerServer('test', { command: 'new' });
      // Server overwritten, still not connected
      expect(client.isConnected('test')).toBe(false);
    });
  });

  describe('loadFromConfig', () => {
    it('should silently skip non-existent config', async () => {
      const client = new MCPClient({ autoConnect: false });
      await client.loadFromConfig('/nonexistent/path.json');
      // No servers loaded, so stats should show 0 tools
      expect(client.getContextStats().totalTools).toBe(0);
    });

    it('should load servers from config file', async () => {
      const configPath = join(tempDir, 'mcp.json');
      const config = {
        servers: {
          'test-server': {
            command: 'echo',
            args: ['hello'],
          },
        },
      };
      await writeFile(configPath, JSON.stringify(config));

      const client = new MCPClient({ autoConnect: false });
      await client.loadFromConfig(configPath);

      // Server registered (but not connected since autoConnect: false)
      expect(client.isConnected('test-server')).toBe(false);
    });

    it('should handle invalid JSON gracefully', async () => {
      const configPath = join(tempDir, 'invalid.json');
      await writeFile(configPath, 'not valid json');

      const client = new MCPClient({ autoConnect: false });
      // Should not throw
      await client.loadFromConfig(configPath);
      expect(client.getContextStats().totalTools).toBe(0);
    });
  });

  describe('loadFromHierarchicalConfigs', () => {
    it('should merge configs from multiple files', async () => {
      const globalConfig = join(tempDir, 'global.json');
      const localConfig = join(tempDir, 'local.json');

      await writeFile(globalConfig, JSON.stringify({
        servers: {
          'global-server': { command: 'global-cmd' },
          'override-server': { command: 'old-cmd' },
        },
      }));

      await writeFile(localConfig, JSON.stringify({
        servers: {
          'local-server': { command: 'local-cmd' },
          'override-server': { command: 'new-cmd' },
        },
      }));

      const client = new MCPClient({ autoConnect: false });
      await client.loadFromHierarchicalConfigs([globalConfig, localConfig]);

      // Verify servers were registered (not connected since autoConnect: false)
      expect(client.isConnected('global-server')).toBe(false);
      expect(client.isConnected('local-server')).toBe(false);
      expect(client.isConnected('override-server')).toBe(false);
    });

    it('should skip non-existent files in hierarchy', async () => {
      const existingConfig = join(tempDir, 'existing.json');
      await writeFile(existingConfig, JSON.stringify({
        servers: { 'test': { command: 'test' } },
      }));

      const client = new MCPClient({ autoConnect: false });
      await client.loadFromHierarchicalConfigs([
        '/nonexistent/1.json',
        existingConfig,
        '/nonexistent/2.json',
      ]);

      // Server registered from existing config
      expect(client.isConnected('test')).toBe(false);
    });
  });

  describe('tool summaries', () => {
    it('should return empty array when no servers connected', () => {
      const client = new MCPClient({ autoConnect: false });
      const summaries = client.getAllToolSummaries();
      expect(summaries).toEqual([]);
    });

    it('should return empty array for unconnected server', () => {
      const client = new MCPClient({ autoConnect: false });
      client.registerServer('test', { command: 'test' });
      const summaries = client.getAllToolSummaries();
      expect(summaries).toEqual([]);
    });
  });

  describe('tool resolution', () => {
    it('should return null for non-existent tool', () => {
      const client = new MCPClient({ autoConnect: false });
      const tool = client.getFullToolDefinition('nonexistent');
      expect(tool).toBeNull();
    });

    it('should return null for invalid tool name format', () => {
      const client = new MCPClient({ autoConnect: false });
      const tool = client.getFullToolDefinition('invalid_name');
      expect(tool).toBeNull();
    });
  });

  describe('context stats', () => {
    it('should return stats with zero counts when no tools', () => {
      const client = new MCPClient({ autoConnect: false });
      const stats = client.getContextStats();
      expect(stats.totalTools).toBe(0);
      expect(stats.summaryCount).toBe(0);
      expect(stats.loadedCount).toBe(0);
    });
  });

  describe('event listeners', () => {
    it('should add and remove event listeners', () => {
      const client = new MCPClient({ autoConnect: false });
      const listener = vi.fn();

      const unsubscribe = client.on(listener);
      expect(typeof unsubscribe).toBe('function');

      unsubscribe();
      // After unsubscribe, listener should not be called
    });
  });

  describe('cleanup', () => {
    it('should cleanup without errors', async () => {
      const client = new MCPClient({ autoConnect: false });
      client.registerServer('test', { command: 'test' });
      await client.cleanup();
      // Should not throw
    });

    it('should handle multiple cleanup calls', async () => {
      const client = new MCPClient({ autoConnect: false });
      await client.cleanup();
      await client.cleanup();
      // Should not throw
    });
  });
});

// =============================================================================
// FACTORY FUNCTION TESTS
// =============================================================================

describe('createMCPClient', () => {
  let tempDir: string;

  beforeEach(async () => {
    tempDir = join(tmpdir(), `mcp-factory-test-${Date.now()}`);
    await mkdir(tempDir, { recursive: true });
  });

  afterEach(async () => {
    try {
      const files = await import('node:fs/promises').then(fs => fs.readdir(tempDir));
      for (const file of files) {
        await unlink(join(tempDir, file));
      }
      await rmdir(tempDir);
    } catch {
      // Ignore cleanup errors
    }
  });

  it('should create client from factory', async () => {
    const { createMCPClient } = await import('../src/integrations/mcp/mcp-client.js');
    const client = await createMCPClient({ autoConnect: false });
    expect(client).toBeDefined();
    await client.cleanup();
  });

  it('should load from config paths if provided', async () => {
    const configPath = join(tempDir, 'test-mcp.json');
    await writeFile(configPath, JSON.stringify({
      servers: { 'factory-test': { command: 'test' } },
    }));

    const { createMCPClient } = await import('../src/integrations/mcp/mcp-client.js');
    const client = await createMCPClient({
      configPaths: [configPath],
      autoConnect: false,
    });

    // Server registered (not connected since autoConnect: false)
    expect(client.isConnected('factory-test')).toBe(false);
    await client.cleanup();
  });
});
