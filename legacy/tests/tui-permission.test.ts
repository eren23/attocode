/**
 * Tests for TUIPermissionChecker
 *
 * Verifies the TUI approval system correctly routes permissions
 * through the approval bridge and handles safety fallbacks.
 */

import { describe, it, expect, vi } from 'vitest';
import { TUIPermissionChecker } from '../src/tools/permission.js';
import type { TUIApprovalBridge } from '../src/adapters.js';
import type { PermissionRequest } from '../src/tools/types.js';

// Create a mock TUI approval bridge
function createMockBridge(options: {
  connected?: boolean;
  approveAll?: boolean;
  denyReason?: string;
}): TUIApprovalBridge {
  const { connected = true, approveAll = true, denyReason } = options;

  return {
    handler: vi.fn().mockResolvedValue({
      approved: approveAll,
      reason: approveAll ? undefined : (denyReason || 'User denied'),
    }),
    connect: vi.fn(),
    resolve: vi.fn(),
    hasPending: vi.fn().mockReturnValue(false),
    isConnected: vi.fn().mockReturnValue(connected),
  };
}

describe('TUIPermissionChecker', () => {
  describe('safe operations', () => {
    it('should auto-approve safe operations without calling bridge', async () => {
      const bridge = createMockBridge({ connected: true });
      const checker = new TUIPermissionChecker(bridge);

      const request: PermissionRequest = {
        tool: 'read_file',
        operation: 'Read file contents',
        target: '/path/to/file.ts',
        dangerLevel: 'safe',
      };

      const result = await checker.check(request);

      expect(result.granted).toBe(true);
      expect(bridge.handler).not.toHaveBeenCalled();
    });

    it('should auto-approve safe operations even when bridge disconnected', async () => {
      const bridge = createMockBridge({ connected: false });
      const checker = new TUIPermissionChecker(bridge);

      const request: PermissionRequest = {
        tool: 'list_files',
        operation: 'List directory',
        target: '/path/to/dir',
        dangerLevel: 'safe',
      };

      const result = await checker.check(request);

      expect(result.granted).toBe(true);
      expect(bridge.handler).not.toHaveBeenCalled();
    });
  });

  describe('dangerous operations with connected bridge', () => {
    it('should route moderate operations to bridge', async () => {
      const bridge = createMockBridge({ connected: true, approveAll: true });
      const checker = new TUIPermissionChecker(bridge);

      const request: PermissionRequest = {
        tool: 'write_file',
        operation: 'Write file',
        target: '/path/to/file.ts',
        dangerLevel: 'moderate',
      };

      const result = await checker.check(request);

      expect(result.granted).toBe(true);
      expect(bridge.handler).toHaveBeenCalledOnce();
      expect(bridge.handler).toHaveBeenCalledWith(
        expect.objectContaining({
          tool: 'write_file',
          risk: 'moderate',
        })
      );
    });

    it('should route dangerous operations to bridge', async () => {
      const bridge = createMockBridge({ connected: true, approveAll: true });
      const checker = new TUIPermissionChecker(bridge);

      const request: PermissionRequest = {
        tool: 'bash',
        operation: 'Execute command',
        target: 'rm -rf /tmp/test',
        dangerLevel: 'dangerous',
      };

      const result = await checker.check(request);

      expect(result.granted).toBe(true);
      expect(bridge.handler).toHaveBeenCalledOnce();
      expect(bridge.handler).toHaveBeenCalledWith(
        expect.objectContaining({
          tool: 'bash',
          risk: 'high',
        })
      );
    });

    it('should route critical operations to bridge', async () => {
      const bridge = createMockBridge({ connected: true, approveAll: true });
      const checker = new TUIPermissionChecker(bridge);

      const request: PermissionRequest = {
        tool: 'bash',
        operation: 'Execute sudo command',
        target: 'sudo rm -rf /',
        dangerLevel: 'critical',
      };

      const result = await checker.check(request);

      expect(result.granted).toBe(true);
      expect(bridge.handler).toHaveBeenCalledWith(
        expect.objectContaining({
          risk: 'critical',
        })
      );
    });

    it('should respect user denial from bridge', async () => {
      const bridge = createMockBridge({
        connected: true,
        approveAll: false,
        denyReason: 'Too risky',
      });
      const checker = new TUIPermissionChecker(bridge);

      const request: PermissionRequest = {
        tool: 'bash',
        operation: 'Execute command',
        target: 'rm -rf /',
        dangerLevel: 'dangerous',
      };

      const result = await checker.check(request);

      expect(result.granted).toBe(false);
      expect(result.reason).toBe('Too risky');
    });
  });

  describe('safety fallback when bridge disconnected', () => {
    it('should block moderate operations when bridge disconnected', async () => {
      const bridge = createMockBridge({ connected: false });
      const checker = new TUIPermissionChecker(bridge);

      const request: PermissionRequest = {
        tool: 'write_file',
        operation: 'Write file',
        target: '/path/to/file.ts',
        dangerLevel: 'moderate',
      };

      const result = await checker.check(request);

      expect(result.granted).toBe(false);
      expect(result.reason).toContain('not ready');
      expect(bridge.handler).not.toHaveBeenCalled();
    });

    it('should block dangerous operations when bridge disconnected', async () => {
      const bridge = createMockBridge({ connected: false });
      const checker = new TUIPermissionChecker(bridge);

      const request: PermissionRequest = {
        tool: 'bash',
        operation: 'Execute command',
        target: 'rm -rf /tmp/test',
        dangerLevel: 'dangerous',
      };

      const result = await checker.check(request);

      expect(result.granted).toBe(false);
      expect(result.reason).toContain('not ready');
      expect(bridge.handler).not.toHaveBeenCalled();
    });

    it('should block critical operations when bridge disconnected', async () => {
      const bridge = createMockBridge({ connected: false });
      const checker = new TUIPermissionChecker(bridge);

      const request: PermissionRequest = {
        tool: 'bash',
        operation: 'Execute sudo command',
        target: 'sudo rm -rf /',
        dangerLevel: 'critical',
      };

      const result = await checker.check(request);

      expect(result.granted).toBe(false);
      expect(result.reason).toContain('not ready');
      expect(bridge.handler).not.toHaveBeenCalled();
    });
  });

  describe('request ID generation', () => {
    it('should generate unique request IDs', async () => {
      const bridge = createMockBridge({ connected: true, approveAll: true });
      const checker = new TUIPermissionChecker(bridge);

      const request: PermissionRequest = {
        tool: 'bash',
        operation: 'test',
        target: 'test',
        dangerLevel: 'moderate',
      };

      await checker.check(request);
      await checker.check(request);

      const calls = (bridge.handler as any).mock.calls;
      const id1 = calls[0][0].id;
      const id2 = calls[1][0].id;

      expect(id1).not.toBe(id2);
      expect(id1).toMatch(/^perm-\d+-[a-z0-9]+$/);
      expect(id2).toMatch(/^perm-\d+-[a-z0-9]+$/);
    });
  });
});
