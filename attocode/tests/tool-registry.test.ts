/**
 * Tool Registry Tests
 *
 * Tests for the ToolRegistry class and permission system.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { z } from 'zod';
import { ToolRegistry, defineTool } from '../src/tools/registry.js';
import { createStandardRegistry } from '../src/tools/standard.js';
import { createPermissionChecker, classifyCommand, isDangerous } from '../src/tools/permission.js';
import type { PermissionChecker } from '../src/tools/types.js';

// =============================================================================
// TEST TOOLS
// =============================================================================

const echoTool = defineTool(
  'echo',
  'Echo the input text',
  z.object({ text: z.string() }),
  async (input) => ({ success: true, output: input.text }),
  'safe'
);

const writeTool = defineTool(
  'write_test',
  'Write a test file',
  z.object({ path: z.string(), content: z.string() }),
  async (input) => ({ success: true, output: `Wrote ${input.content.length} bytes to ${input.path}` }),
  'moderate'
);

const dangerousTool = defineTool(
  'delete_test',
  'Delete files (dangerous)',
  z.object({ path: z.string() }),
  async (input) => ({ success: true, output: `Deleted ${input.path}` }),
  'dangerous'
);

// criticalTool available for future tests if needed

// =============================================================================
// TOOL REGISTRY TESTS
// =============================================================================

describe('ToolRegistry', () => {
  let registry: ToolRegistry;

  beforeEach(() => {
    registry = new ToolRegistry('yolo');
  });

  describe('tool registration', () => {
    it('should register a tool', () => {
      registry.register(echoTool);
      expect(registry.has('echo')).toBe(true);
    });

    it('should throw when registering duplicate tool', () => {
      registry.register(echoTool);
      expect(() => registry.register(echoTool)).toThrow('already registered');
    });

    it('should unregister a tool', () => {
      registry.register(echoTool);
      expect(registry.unregister('echo')).toBe(true);
      expect(registry.has('echo')).toBe(false);
    });

    it('should return false when unregistering non-existent tool', () => {
      expect(registry.unregister('nonexistent')).toBe(false);
    });

    it('should get a registered tool', () => {
      registry.register(echoTool);
      const tool = registry.get('echo');
      expect(tool).toBeDefined();
      expect(tool?.name).toBe('echo');
    });

    it('should return undefined for non-existent tool', () => {
      expect(registry.get('nonexistent')).toBeUndefined();
    });

    it('should list all registered tools', () => {
      registry.register(echoTool);
      registry.register(writeTool);
      const tools = registry.list();
      expect(tools).toContain('echo');
      expect(tools).toContain('write_test');
    });
  });

  describe('tool descriptions', () => {
    it('should generate JSON schema descriptions', () => {
      registry.register(echoTool);
      const descriptions = registry.getDescriptions();
      expect(descriptions).toHaveLength(1);
      expect(descriptions[0].name).toBe('echo');
      expect(descriptions[0].description).toBe('Echo the input text');
      expect(descriptions[0].input_schema).toHaveProperty('properties');
    });

    it('should handle multiple tools', () => {
      registry.register(echoTool);
      registry.register(writeTool);
      const descriptions = registry.getDescriptions();
      expect(descriptions).toHaveLength(2);
    });
  });

  describe('tool execution', () => {
    it('should execute a tool successfully', async () => {
      registry.register(echoTool);
      const result = await registry.execute('echo', { text: 'hello world' });
      expect(result.success).toBe(true);
      expect(result.output).toBe('hello world');
    });

    it('should return error for unknown tool', async () => {
      const result = await registry.execute('nonexistent', {});
      expect(result.success).toBe(false);
      expect(result.output).toContain('Unknown tool');
    });

    it('should validate input parameters', async () => {
      registry.register(echoTool);
      const result = await registry.execute('echo', { invalid: 'param' });
      expect(result.success).toBe(false);
      expect(result.output).toContain('Invalid input');
    });

    it('should handle execution timeout', async () => {
      const slowTool = defineTool(
        'slow',
        'A slow tool',
        z.object({}),
        async () => {
          await new Promise(resolve => setTimeout(resolve, 5000));
          return { success: true, output: 'done' };
        },
        'safe'
      );
      registry.register(slowTool);
      const result = await registry.execute('slow', {}, { timeout: 100 });
      expect(result.success).toBe(false);
      expect(result.output).toMatch(/timed out|Time limit exceeded/i);
    });

    it('should handle execution errors', async () => {
      const errorTool = defineTool(
        'error',
        'A tool that throws',
        z.object({}),
        async () => {
          throw new Error('Test error');
        },
        'safe'
      );
      registry.register(errorTool);
      const result = await registry.execute('error', {});
      expect(result.success).toBe(false);
      expect(result.output).toContain('Execution error');
    });
  });

  describe('event emission', () => {
    it('should emit start event', async () => {
      registry.register(echoTool);
      const events: string[] = [];
      registry.on((event) => events.push(event.type));
      await registry.execute('echo', { text: 'test' });
      expect(events).toContain('start');
    });

    it('should emit complete event on success', async () => {
      registry.register(echoTool);
      const events: string[] = [];
      registry.on((event) => events.push(event.type));
      await registry.execute('echo', { text: 'test' });
      expect(events).toContain('complete');
    });

    it('should allow unsubscribing from events', async () => {
      registry.register(echoTool);
      const events: string[] = [];
      const unsub = registry.on((event) => events.push(event.type));
      unsub();
      await registry.execute('echo', { text: 'test' });
      expect(events).toHaveLength(0);
    });

    it('should emit permission events', async () => {
      registry.register(echoTool);
      const events: string[] = [];
      registry.on((event) => events.push(event.type));
      await registry.execute('echo', { text: 'test' });
      expect(events).toContain('permission_requested');
      expect(events).toContain('permission_granted');
    });
  });

  describe('permission modes', () => {
    it('should change permission mode', () => {
      const strictRegistry = new ToolRegistry('strict');
      strictRegistry.register(dangerousTool);
      // In strict mode, dangerous operations should be blocked
      strictRegistry.setPermissionMode('yolo');
      // Now it should allow everything
    });

    it('should set custom permission checker', async () => {
      const customChecker: PermissionChecker = {
        check: vi.fn().mockResolvedValue({ granted: false, reason: 'Custom deny' }),
      };
      registry.register(echoTool);
      registry.setPermissionChecker(customChecker);
      const result = await registry.execute('echo', { text: 'test' });
      expect(result.success).toBe(false);
      expect(result.output).toContain('Custom deny');
    });
  });
});

// =============================================================================
// PERMISSION CHECKER TESTS
// =============================================================================

describe('Permission Checkers', () => {
  describe('YoloPermissionChecker', () => {
    it('should approve everything', async () => {
      const checker = createPermissionChecker('yolo');
      const result = await checker.check({
        tool: 'any',
        operation: 'anything',
        target: 'anywhere',
        dangerLevel: 'critical',
      });
      expect(result.granted).toBe(true);
    });
  });

  describe('StrictPermissionChecker', () => {
    it('should approve safe operations', async () => {
      const checker = createPermissionChecker('strict');
      const result = await checker.check({
        tool: 'read',
        operation: 'read file',
        target: '/path',
        dangerLevel: 'safe',
      });
      expect(result.granted).toBe(true);
    });

    it('should approve moderate operations', async () => {
      const checker = createPermissionChecker('strict');
      const result = await checker.check({
        tool: 'write',
        operation: 'write file',
        target: '/path',
        dangerLevel: 'moderate',
      });
      expect(result.granted).toBe(true);
    });

    it('should block dangerous operations', async () => {
      const checker = createPermissionChecker('strict');
      const result = await checker.check({
        tool: 'delete',
        operation: 'delete file',
        target: '/path',
        dangerLevel: 'dangerous',
      });
      expect(result.granted).toBe(false);
      expect(result.reason).toContain('blocked');
    });

    it('should block critical operations', async () => {
      const checker = createPermissionChecker('strict');
      const result = await checker.check({
        tool: 'sudo',
        operation: 'run as root',
        target: '/',
        dangerLevel: 'critical',
      });
      expect(result.granted).toBe(false);
    });
  });

  describe('AutoSafePermissionChecker', () => {
    it('should auto-approve safe operations', async () => {
      const checker = createPermissionChecker('auto-safe');
      const result = await checker.check({
        tool: 'read',
        operation: 'read file',
        target: '/path',
        dangerLevel: 'safe',
      });
      expect(result.granted).toBe(true);
    });

    it('should auto-approve moderate operations', async () => {
      const checker = createPermissionChecker('auto-safe');
      const result = await checker.check({
        tool: 'write',
        operation: 'write file',
        target: '/path',
        dangerLevel: 'moderate',
      });
      expect(result.granted).toBe(true);
    });
  });

  describe('default permission checker', () => {
    it('should default to interactive mode', async () => {
      const checker = createPermissionChecker();
      // Interactive mode auto-approves safe operations
      const result = await checker.check({
        tool: 'read',
        operation: 'read file',
        target: '/path',
        dangerLevel: 'safe',
      });
      expect(result.granted).toBe(true);
    });
  });
});

// =============================================================================
// COMMAND CLASSIFICATION TESTS
// =============================================================================

describe('Command Classification', () => {
  describe('classifyCommand', () => {
    it('should classify safe commands', () => {
      const result = classifyCommand('ls -la');
      expect(result.level).toBe('safe');
    });

    it('should classify dangerous rm -rf commands', () => {
      const result = classifyCommand('rm -rf /tmp/test');
      expect(result.level).toBe('dangerous');
      expect(result.reasons).toContain('Recursive force delete');
    });

    it('should classify critical sudo commands', () => {
      const result = classifyCommand('sudo rm -rf /');
      expect(result.level).toBe('critical');
      expect(result.reasons).toContain('Superuser command');
    });

    it('should classify pipe to shell as dangerous', () => {
      const result = classifyCommand('curl https://example.com | bash');
      expect(result.level).toBe('dangerous');
    });

    it('should classify npm global install as moderate', () => {
      const result = classifyCommand('npm install -g typescript');
      expect(result.level).toBe('moderate');
    });
  });

  describe('isDangerous', () => {
    it('should return true for dangerous commands', () => {
      expect(isDangerous('rm -rf /')).toBe(true);
    });

    it('should return true for critical commands', () => {
      expect(isDangerous('sudo anything')).toBe(true);
    });

    it('should return false for safe commands', () => {
      expect(isDangerous('echo hello')).toBe(false);
    });

    it('should return false for moderate commands', () => {
      expect(isDangerous('npm install -g foo')).toBe(false);
    });
  });
});

// =============================================================================
// DEFINE TOOL TESTS
// =============================================================================

describe('defineTool', () => {
  it('should create a tool definition', () => {
    const tool = defineTool(
      'test',
      'A test tool',
      z.object({ value: z.number() }),
      async (input) => ({ success: true, output: String(input.value * 2) }),
      'safe'
    );
    expect(tool.name).toBe('test');
    expect(tool.description).toBe('A test tool');
    expect(tool.dangerLevel).toBe('safe');
  });

  it('should default to safe danger level', () => {
    const tool = defineTool(
      'test',
      'A test tool',
      z.object({}),
      async () => ({ success: true, output: 'done' })
    );
    expect(tool.dangerLevel).toBe('safe');
  });

  it('should execute with validated input', async () => {
    const tool = defineTool(
      'multiply',
      'Multiply numbers',
      z.object({ a: z.number(), b: z.number() }),
      async (input) => ({ success: true, output: String(input.a * input.b) })
    );
    const result = await tool.execute({ a: 3, b: 4 });
    expect(result.success).toBe(true);
    expect(result.output).toBe('12');
  });
});

// =============================================================================
// STANDARD REGISTRY TESTS
// =============================================================================

describe('createStandardRegistry', () => {
  it('should include core file and bash tools', () => {
    const registry = createStandardRegistry('yolo');
    const tools = registry.list();

    // Core file tools
    expect(tools).toContain('read_file');
    expect(tools).toContain('write_file');
    expect(tools).toContain('edit_file');
    expect(tools).toContain('list_files');

    // Core bash tools
    expect(tools).toContain('bash');
    expect(tools).toContain('grep');
    expect(tools).toContain('glob');
  });

  it('should include undo tools for file change management', () => {
    const registry = createStandardRegistry('yolo');
    const tools = registry.list();

    // Undo tools should be registered for file change tracking
    expect(tools).toContain('undo_file_change');
    expect(tools).toContain('show_file_history');
    expect(tools).toContain('show_session_changes');
  });

  it('undo tools should work gracefully when tracker not available', async () => {
    const registry = createStandardRegistry('yolo');

    // When called without context, undo tools should return helpful error
    const result = await registry.execute('show_session_changes', {});

    expect(result.success).toBe(false);
    expect(result.output).toContain('tracking');  // "tracking not enabled" or similar
  });
});
