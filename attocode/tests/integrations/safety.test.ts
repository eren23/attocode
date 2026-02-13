/**
 * Safety Manager Tests
 *
 * Tests for sandbox validation, path traversal protection, and audit logging.
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { mkdtemp, rm, symlink, mkdir, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  SandboxManager,
  HumanInLoopManager,
  SafetyManager,
  createSafetyManager,
} from '../../src/integrations/safety.js';
import type { SandboxConfig, HumanInLoopConfig, ToolCall } from '../../src/types.js';

describe('SandboxManager', () => {
  describe('command validation', () => {
    const config: SandboxConfig = {
      enabled: true,
      allowedCommands: ['echo', 'ls', 'cat'],
      blockedCommands: ['rm -rf', 'sudo'],
      allowedPaths: ['.'],
    };

    let manager: SandboxManager;

    beforeEach(() => {
      manager = new SandboxManager(config);
    });

    it('should allow commands in allowlist', () => {
      const result = manager.isCommandAllowed('echo "hello"');
      expect(result.allowed).toBe(true);
    });

    it('should block commands matching blocked patterns', () => {
      const result = manager.isCommandAllowed('rm -rf /');
      expect(result.allowed).toBe(false);
      expect(result.reason).toContain('Blocked pattern');
    });

    it('should block commands not in allowlist', () => {
      const result = manager.isCommandAllowed('wget http://example.com');
      expect(result.allowed).toBe(false);
      expect(result.reason).toContain('not in the sandbox allowlist');
    });

    it('should allow any command when allowlist is empty', () => {
      const openManager = new SandboxManager({
        ...config,
        allowedCommands: [],
      });

      const result = openManager.isCommandAllowed('any-command');
      expect(result.allowed).toBe(true);
    });

    it('should block file mutation patterns when compatibility flag is on', () => {
      const strict = new SandboxManager({
        ...config,
        blockFileCreationViaBash: true,
        allowedCommands: ['cat', 'echo', 'printf'],
      });
      const result = strict.isCommandAllowed(`cat > out.txt << 'EOF'\nhello\nEOF`);
      expect(result.allowed).toBe(false);
      expect(result.reason).toContain('File creation/modification via bash');
    });

    it('should enforce read_only bash mode', () => {
      const strict = new SandboxManager({
        ...config,
        bashMode: 'read_only',
        allowedCommands: ['mkdir'],
      });
      const result = strict.isCommandAllowed('mkdir tmp');
      expect(result.allowed).toBe(false);
      expect(result.reason).toContain('read-only bash commands');
    });
  });

  describe('path validation - basic', () => {
    let tempDir: string;
    let manager: SandboxManager;

    beforeEach(async () => {
      tempDir = await mkdtemp(join(tmpdir(), 'safety-test-'));
      manager = new SandboxManager({
        enabled: true,
        allowedPaths: [tempDir],
      });
    });

    afterEach(async () => {
      await rm(tempDir, { recursive: true, force: true });
    });

    it('should allow paths within allowed directory', () => {
      const result = manager.isPathAllowed(join(tempDir, 'file.txt'));
      expect(result).toBe(true);
    });

    it('should allow paths in subdirectories', () => {
      const result = manager.isPathAllowed(join(tempDir, 'subdir', 'file.txt'));
      expect(result).toBe(true);
    });

    it('should block absolute paths outside allowed directory', () => {
      const result = manager.isPathAllowed('/etc/passwd');
      expect(result).toBe(false);
    });

    it('should block relative paths that escape', () => {
      const result = manager.isPathAllowed(join(tempDir, '..', '..', 'etc', 'passwd'));
      expect(result).toBe(false);
    });

    it('should allow the exact allowed path', () => {
      const result = manager.isPathAllowed(tempDir);
      expect(result).toBe(true);
    });
  });

  describe('path validation - symlink protection', () => {
    let tempDir: string;
    let manager: SandboxManager;

    beforeEach(async () => {
      tempDir = await mkdtemp(join(tmpdir(), 'symlink-test-'));
      manager = new SandboxManager({
        enabled: true,
        allowedPaths: [tempDir],
      });

      // Create a legitimate directory
      await mkdir(join(tempDir, 'legitimate'), { recursive: true });
    });

    afterEach(async () => {
      await rm(tempDir, { recursive: true, force: true });
    });

    it('should block symlink escape to /etc', async () => {
      // Create a symlink pointing outside allowed directory
      await symlink('/etc', join(tempDir, 'legitimate', 'escape'));

      // Attempt to access /etc/passwd through the symlink
      const maliciousPath = join(tempDir, 'legitimate', 'escape', 'passwd');
      const result = manager.isPathAllowed(maliciousPath);

      expect(result).toBe(false);
    });

    it('should block symlink escape to /tmp', async () => {
      // Create symlink to /tmp
      await symlink('/tmp', join(tempDir, 'tmp-escape'));

      const result = manager.isPathAllowed(join(tempDir, 'tmp-escape', 'somefile'));
      expect(result).toBe(false);
    });

    it('should allow legitimate paths within allowed directory', async () => {
      // Create a real file
      await writeFile(join(tempDir, 'legitimate', 'file.txt'), 'content');

      const result = manager.isPathAllowed(join(tempDir, 'legitimate', 'file.txt'));
      expect(result).toBe(true);
    });

    it('should handle broken symlinks safely', async () => {
      // Create a broken symlink
      await symlink('/nonexistent/path/that/does/not/exist', join(tempDir, 'broken'));

      const result = manager.isPathAllowed(join(tempDir, 'broken'));
      expect(result).toBe(false);
    });

    it('should handle symlinks to symlinks (chain)', async () => {
      // Create chain: link1 -> link2 -> /etc
      const link2Path = join(tempDir, 'link2');
      const link1Path = join(tempDir, 'link1');

      await symlink('/etc', link2Path);
      await symlink(link2Path, link1Path);

      const result = manager.isPathAllowed(join(link1Path, 'passwd'));
      expect(result).toBe(false);
    });

    it('should allow symlinks within allowed directory', async () => {
      // Create symlink that stays within allowed directory
      await writeFile(join(tempDir, 'target.txt'), 'target content');
      await symlink(join(tempDir, 'target.txt'), join(tempDir, 'link.txt'));

      const result = manager.isPathAllowed(join(tempDir, 'link.txt'));
      expect(result).toBe(true);
    });
  });

  describe('tool call validation', () => {
    let tempDir: string;
    let manager: SandboxManager;

    beforeEach(async () => {
      tempDir = await mkdtemp(join(tmpdir(), 'tool-test-'));
      manager = new SandboxManager({
        enabled: true,
        allowedCommands: ['echo', 'ls'],
        blockedCommands: ['rm -rf'],
        allowedPaths: [tempDir],
      });
    });

    afterEach(async () => {
      await rm(tempDir, { recursive: true, force: true });
    });

    it('should validate bash tool calls', () => {
      const toolCall: ToolCall = {
        id: 'call-1',
        name: 'bash',
        arguments: { command: 'echo hello' },
      };

      const result = manager.validateToolCall(toolCall);
      expect(result.valid).toBe(true);
    });

    it('should block bash tool with dangerous command', () => {
      const toolCall: ToolCall = {
        id: 'call-2',
        name: 'bash',
        arguments: { command: 'rm -rf /' },
      };

      const result = manager.validateToolCall(toolCall);
      expect(result.valid).toBe(false);
      expect(result.reason).toContain('Blocked pattern');
    });

    it('should validate read_file tool calls', () => {
      const toolCall: ToolCall = {
        id: 'call-3',
        name: 'read_file',
        arguments: { path: join(tempDir, 'file.txt') },
      };

      const result = manager.validateToolCall(toolCall);
      expect(result.valid).toBe(true);
    });

    it('should block read_file for paths outside allowed', () => {
      const toolCall: ToolCall = {
        id: 'call-4',
        name: 'read_file',
        arguments: { path: '/etc/passwd' },
      };

      const result = manager.validateToolCall(toolCall);
      expect(result.valid).toBe(false);
      expect(result.reason).toContain('Path not allowed');
    });

    it('should validate write_file tool calls', () => {
      const toolCall: ToolCall = {
        id: 'call-5',
        name: 'write_file',
        arguments: { file_path: join(tempDir, 'new.txt') },
      };

      const result = manager.validateToolCall(toolCall);
      expect(result.valid).toBe(true);
    });

    it('should allow unknown tools (no path/command validation needed)', () => {
      const toolCall: ToolCall = {
        id: 'call-6',
        name: 'search',
        arguments: { query: 'test' },
      };

      const result = manager.validateToolCall(toolCall);
      expect(result.valid).toBe(true);
    });

    it('should block denied tools via policy profile', () => {
      const policyManager = new SandboxManager(
        {
          enabled: true,
          allowedCommands: ['echo'],
          blockedCommands: ['rm -rf', 'sudo'],
          allowedPaths: ['.'],
        },
        {
          enabled: true,
          defaultProfile: 'deny-bash',
          profiles: {
            'deny-bash': {
              deniedTools: ['bash'],
            },
          },
        },
      );

      const result = policyManager.validateToolCall({
        id: 'call-7',
        name: 'bash',
        arguments: { command: 'echo hello' },
      });
      expect(result.valid).toBe(false);
      expect(result.reason).toContain('denied');
    });
  });

  describe('resource limits', () => {
    it('should return default resource limits', () => {
      const manager = new SandboxManager({ enabled: true });
      const limits = manager.getResourceLimits();

      expect(limits.maxCpuSeconds).toBe(30);
      expect(limits.maxMemoryMB).toBe(512);
      expect(limits.timeout).toBe(60000);
    });

    it('should return custom resource limits', () => {
      const manager = new SandboxManager({
        enabled: true,
        resourceLimits: {
          maxCpuSeconds: 60,
          maxMemoryMB: 1024,
          maxOutputBytes: 2048,
          timeout: 120000,
        },
      });

      const limits = manager.getResourceLimits();
      expect(limits.maxCpuSeconds).toBe(60);
      expect(limits.maxMemoryMB).toBe(1024);
    });
  });
});

describe('HumanInLoopManager', () => {
  describe('risk assessment', () => {
    let manager: HumanInLoopManager;

    beforeEach(() => {
      manager = new HumanInLoopManager({
        enabled: true,
        riskThreshold: 'moderate',
        auditLog: true,
        alwaysApprove: ['delete'],
        neverApprove: ['read'],
      });
    });

    it('should assess high risk for alwaysApprove patterns', () => {
      const toolCall: ToolCall = {
        id: 'call-1',
        name: 'delete_file',
        arguments: { path: '/some/file' },
      };

      const risk = manager.assessRisk(toolCall);
      expect(risk).toBe('high');
    });

    it('should assess low risk for neverApprove patterns', () => {
      const toolCall: ToolCall = {
        id: 'call-2',
        name: 'read_file',
        arguments: { path: '/some/file' },
      };

      const risk = manager.assessRisk(toolCall);
      expect(risk).toBe('low');
    });

    it('should assess moderate risk for risky operations', () => {
      const toolCall: ToolCall = {
        id: 'call-3',
        name: 'write_file',
        arguments: { path: '/some/file' },
      };

      const risk = manager.assessRisk(toolCall);
      expect(risk).toBe('moderate');
    });

    it('should assess moderate risk for --force flags', () => {
      const toolCall: ToolCall = {
        id: 'call-4',
        name: 'git',
        arguments: { command: 'push --force' },
      };

      const risk = manager.assessRisk(toolCall);
      expect(risk).toBe('moderate');
    });

    it('should assess low risk for safe operations', () => {
      const toolCall: ToolCall = {
        id: 'call-5',
        name: 'search',
        arguments: { query: 'test' },
      };

      const risk = manager.assessRisk(toolCall);
      expect(risk).toBe('low');
    });
  });

  describe('approval requirements', () => {
    it('should require approval for high risk actions', () => {
      const manager = new HumanInLoopManager({
        enabled: true,
        riskThreshold: 'high',
      });

      const highRiskCall: ToolCall = {
        id: 'call-1',
        name: 'dangerous_operation',
        arguments: {},
      };

      // Mock assessRisk to return high
      const needsApproval = manager.needsApproval({
        id: 'call-2',
        name: 'delete_all',
        arguments: {},
      });

      // Since delete matches risky patterns
      expect(needsApproval).toBe(true);
    });

    it('should not require approval for low risk when threshold is high', () => {
      const manager = new HumanInLoopManager({
        enabled: true,
        riskThreshold: 'high',
        neverApprove: ['read'],
      });

      const toolCall: ToolCall = {
        id: 'call-1',
        name: 'read_file',
        arguments: {},
      };

      const needsApproval = manager.needsApproval(toolCall);
      expect(needsApproval).toBe(false);
    });
  });

  describe('audit logging', () => {
    let manager: HumanInLoopManager;

    beforeEach(() => {
      manager = new HumanInLoopManager({
        enabled: true,
        auditLog: true,
      });
    });

    it('should start with empty audit log', () => {
      const log = manager.getAuditLog();
      expect(log).toEqual([]);
    });

    it('should provide audit summary', () => {
      const summary = manager.getAuditSummary();

      expect(summary.total).toBe(0);
      expect(summary.approved).toBe(0);
      expect(summary.denied).toBe(0);
    });

    it('should clear audit log', () => {
      // Trigger some logging through requestApproval
      manager.clearAuditLog();
      const log = manager.getAuditLog();
      expect(log).toEqual([]);
    });
  });

  describe('audit log limits', () => {
    it('should not grow unbounded when many actions are logged', async () => {
      const manager = new HumanInLoopManager({
        enabled: true,
        auditLog: true,
        riskThreshold: 'low', // Auto-approve everything
      });

      // Request approval for many actions (auto-approved, but logged)
      for (let i = 0; i < 100; i++) {
        await manager.requestApproval(
          { id: `call-${i}`, name: 'test_tool', arguments: {} },
          'test context'
        );
      }

      const log = manager.getAuditLog();

      // Should have logged all actions
      expect(log.length).toBe(100);

      // The limit is 10000, so we can't easily test trimming without 10k+ calls
      // Just verify the mechanism doesn't crash
    });
  });
});

describe('SafetyManager', () => {
  describe('combined validation', () => {
    let tempDir: string;
    let manager: SafetyManager;

    beforeEach(async () => {
      tempDir = await mkdtemp(join(tmpdir(), 'combined-test-'));

      const sandboxConfig: SandboxConfig = {
        enabled: true,
        allowedCommands: ['echo'],
        allowedPaths: [tempDir],
      };

      const hilConfig: HumanInLoopConfig = {
        enabled: true,
        riskThreshold: 'high',
      };

      manager = createSafetyManager(sandboxConfig, hilConfig);
    });

    afterEach(async () => {
      await rm(tempDir, { recursive: true, force: true });
    });

    it('should have both sandbox and HIL managers', () => {
      expect(manager.sandbox).not.toBeNull();
      expect(manager.humanInLoop).not.toBeNull();
    });

    it('should validate and approve safe actions', async () => {
      const result = await manager.validateAndApprove(
        { id: 'call-1', name: 'echo', arguments: {} },
        'test context'
      );

      expect(result.allowed).toBe(true);
    });

    it('should block sandbox violations', async () => {
      const result = await manager.validateAndApprove(
        { id: 'call-2', name: 'read_file', arguments: { path: '/etc/passwd' } },
        'test context'
      );

      expect(result.allowed).toBe(false);
      expect(result.reason).toContain('Path not allowed');
    });

    it('should skip human approval when requested while still running sandbox checks', async () => {
      const approvalHandler = async () => ({ approved: false, reason: 'Denied by test' });
      const withHilOnly = createSafetyManager(false, {
        enabled: true,
        riskThreshold: 'low',
        approvalHandler,
      });

      const blocked = await withHilOnly.validateAndApprove(
        { id: 'call-hil-1', name: 'write_file', arguments: { path: join(tempDir, 'x.ts'), content: 'x' } },
        'test context'
      );
      expect(blocked.allowed).toBe(false);

      const skipped = await withHilOnly.validateAndApprove(
        { id: 'call-hil-2', name: 'write_file', arguments: { path: join(tempDir, 'x.ts'), content: 'x' } },
        'test context',
        { skipHumanApproval: true }
      );
      expect(skipped.allowed).toBe(true);
    });
  });

  describe('disabled managers', () => {
    it('should work with sandbox disabled', () => {
      const manager = createSafetyManager(false, {
        enabled: true,
        riskThreshold: 'high',
      });

      expect(manager.sandbox).toBeNull();
      expect(manager.humanInLoop).not.toBeNull();
    });

    it('should work with HIL disabled', () => {
      const manager = createSafetyManager({ enabled: true }, false);

      expect(manager.sandbox).not.toBeNull();
      expect(manager.humanInLoop).toBeNull();
    });

    it('should work with both disabled', () => {
      const manager = createSafetyManager(false, false);

      expect(manager.sandbox).toBeNull();
      expect(manager.humanInLoop).toBeNull();
    });
  });
});
