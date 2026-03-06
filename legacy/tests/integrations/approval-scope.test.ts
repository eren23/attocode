/**
 * Unit tests for ApprovalScope (Improvement P6).
 *
 * Tests the pre-approval system that reduces user interruptions
 * during multi-agent workflows by pre-approving safe operations.
 */

import { describe, it, expect } from 'vitest';
import { HumanInLoopManager } from '../../src/integrations/safety/safety.js';
import type { ToolCall } from '../../src/types.js';

function makeToolCall(name: string, args: Record<string, unknown> = {}): ToolCall {
  return { id: `call-${name}`, name, arguments: args };
}

describe('ApprovalScope', () => {
  function createManager(riskThreshold: 'low' | 'moderate' | 'high' = 'moderate') {
    return new HumanInLoopManager({
      enabled: true,
      riskThreshold,
    });
  }

  describe('autoApprove', () => {
    it('should auto-approve listed tools', () => {
      const mgr = createManager();
      mgr.setApprovalScope({
        autoApprove: ['read_file', 'glob', 'grep'],
      });

      expect(mgr.needsApproval(makeToolCall('read_file', { path: '/any/path.ts' }))).toBe(false);
      expect(mgr.needsApproval(makeToolCall('glob', { pattern: '**/*.ts' }))).toBe(false);
      expect(mgr.needsApproval(makeToolCall('grep', { pattern: 'foo' }))).toBe(false);
    });

    it('should use exact match, not substring', () => {
      const mgr = createManager();
      mgr.setApprovalScope({
        autoApprove: ['write_file'],
      });

      // "write_file" should match "write_file" exactly — auto-approved
      expect(mgr.needsApproval(makeToolCall('write_file', { path: 'src/main.ts' }))).toBe(false);
      // "write_file_safe" should NOT be auto-approved by "write_file" (not exact)
      // Since it's a moderate-risk tool (write in name), it needs approval
      expect(mgr.needsApproval(makeToolCall('write_file_safe', { path: 'src/main.ts' }))).toBe(true);
    });

    it('should be case-insensitive', () => {
      const mgr = createManager();
      mgr.setApprovalScope({
        autoApprove: ['Read_File'],
      });

      expect(mgr.needsApproval(makeToolCall('read_file', { path: '/test.ts' }))).toBe(false);
    });
  });

  describe('requireApproval', () => {
    it('should override autoApprove (highest priority)', () => {
      const mgr = createManager();
      mgr.setApprovalScope({
        autoApprove: ['bash'],
        requireApproval: ['bash'],
      });

      // requireApproval takes precedence over autoApprove
      // For a high-risk tool like bash, needsApproval should return true
      expect(mgr.needsApproval(makeToolCall('bash', { command: 'rm -rf /' }))).toBe(true);
    });

    it('should use exact match, not substring', () => {
      const mgr = createManager();
      mgr.setApprovalScope({
        requireApproval: ['bash'],
        autoApprove: ['bash_completion'],
      });

      // "bash" in requireApproval should not block "bash_completion"
      expect(mgr.needsApproval(makeToolCall('bash_completion', {}))).toBe(false);
    });
  });

  describe('scopedApprove', () => {
    it('should approve writes within specified directories', () => {
      const mgr = createManager();
      mgr.setApprovalScope({
        scopedApprove: {
          write_file: { paths: ['src/'] },
        },
      });

      expect(mgr.needsApproval(makeToolCall('write_file', { path: 'src/main.ts' }))).toBe(false);
      expect(mgr.needsApproval(makeToolCall('write_file', { path: 'src/utils/helper.ts' }))).toBe(false);
    });

    it('should not approve writes outside specified directories', () => {
      const mgr = createManager();
      mgr.setApprovalScope({
        scopedApprove: {
          write_file: { paths: ['src/'] },
        },
      });

      // write_file is a moderate risk action, should need approval when outside scope
      expect(mgr.needsApproval(makeToolCall('write_file', { path: 'config/settings.json' }))).toBe(true);
    });

    it('should handle directory boundary correctly', () => {
      const mgr = createManager();
      mgr.setApprovalScope({
        scopedApprove: {
          write_file: { paths: ['src'] }, // No trailing slash
        },
      });

      // Should match src/file.ts (inside src directory)
      expect(mgr.needsApproval(makeToolCall('write_file', { path: 'src/file.ts' }))).toBe(false);
      // Should NOT match src-backup/file.ts (different directory)
      expect(mgr.needsApproval(makeToolCall('write_file', { path: 'src-backup/file.ts' }))).toBe(true);
    });

    it('should handle glob-style /** patterns', () => {
      const mgr = createManager();
      mgr.setApprovalScope({
        scopedApprove: {
          edit_file: { paths: ['tests/**'] },
        },
      });

      expect(mgr.needsApproval(makeToolCall('edit_file', { file_path: 'tests/unit/foo.test.ts' }))).toBe(false);
    });

    it('should support file_path argument', () => {
      const mgr = createManager();
      mgr.setApprovalScope({
        scopedApprove: {
          edit_file: { paths: ['src/'] },
        },
      });

      // edit_file uses file_path, not path
      expect(mgr.needsApproval(makeToolCall('edit_file', { file_path: 'src/agent.ts' }))).toBe(false);
    });

    it('should require approval when no file path in arguments', () => {
      const mgr = createManager();
      mgr.setApprovalScope({
        scopedApprove: {
          write_file: { paths: ['src/'] },
        },
      });

      // No path argument — can't verify scope, should need approval
      expect(mgr.needsApproval(makeToolCall('write_file', {}))).toBe(true);
    });

    it('should support multiple paths', () => {
      const mgr = createManager();
      mgr.setApprovalScope({
        scopedApprove: {
          write_file: { paths: ['src/', 'tests/', 'tools/'] },
        },
      });

      expect(mgr.needsApproval(makeToolCall('write_file', { path: 'src/main.ts' }))).toBe(false);
      expect(mgr.needsApproval(makeToolCall('write_file', { path: 'tests/foo.test.ts' }))).toBe(false);
      expect(mgr.needsApproval(makeToolCall('write_file', { path: 'tools/build.ts' }))).toBe(false);
      expect(mgr.needsApproval(makeToolCall('write_file', { path: 'docs/readme.md' }))).toBe(true);
    });
  });

  describe('no scope set', () => {
    it('should use normal risk-based approval when no scope is set', () => {
      const mgr = createManager('moderate');

      // write_file is moderate risk — should need approval at moderate threshold
      expect(mgr.needsApproval(makeToolCall('write_file', { path: 'src/main.ts' }))).toBe(true);
    });
  });

  describe('priority ordering', () => {
    it('requireApproval > autoApprove > scopedApprove > risk assessment', () => {
      const mgr = createManager();
      mgr.setApprovalScope({
        requireApproval: ['delete_file'],
        autoApprove: ['read_file'],
        scopedApprove: {
          write_file: { paths: ['src/'] },
        },
      });

      // requireApproval: always blocked regardless of risk
      expect(mgr.needsApproval(makeToolCall('delete_file', { path: 'src/main.ts' }))).toBe(true);

      // autoApprove: always approved
      expect(mgr.needsApproval(makeToolCall('read_file', { path: '/anywhere.ts' }))).toBe(false);

      // scopedApprove: approved within scope
      expect(mgr.needsApproval(makeToolCall('write_file', { path: 'src/main.ts' }))).toBe(false);

      // scopedApprove: denied outside scope (falls through to risk assessment)
      expect(mgr.needsApproval(makeToolCall('write_file', { path: 'config/x.json' }))).toBe(true);
    });
  });
});
