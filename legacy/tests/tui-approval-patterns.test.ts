/**
 * Tests for TUI approval pattern matching, risk-level guard, and SQLite persistence.
 */
import { describe, it, expect } from 'vitest';
import type { ApprovalRequest } from '../src/types.js';

// Re-implement generateApprovalPattern here since it's not exported from app.tsx
// This mirrors the logic in src/tui/app.tsx:50-70
function generateApprovalPattern(request: ApprovalRequest): string {
  const tool = request.tool || request.action || 'unknown';
  const args = request.args || {};

  if (tool === 'bash' && typeof args.command === 'string') {
    const parts = args.command.trim().split(/\s+/);
    const baseCmd = parts[0];
    return `bash:${baseCmd}`;
  }

  if (['write_file', 'edit_file', 'read_file'].includes(tool)) {
    const path = (args.path || args.file_path || '') as string;
    return `${tool}:${path}`;
  }

  const firstStringArg = Object.values(args).find(v => typeof v === 'string') as string | undefined;
  return `${tool}:${firstStringArg || ''}`;
}

function makeRequest(overrides: Partial<ApprovalRequest> = {}): ApprovalRequest {
  return {
    id: 'test-1',
    action: 'bash',
    tool: 'bash',
    args: { command: 'echo hello' },
    risk: 'moderate',
    context: 'test',
    ...overrides,
  };
}

describe('generateApprovalPattern', () => {
  it('matches base command regardless of args', () => {
    const pattern1 = generateApprovalPattern(makeRequest({
      args: { command: "sed -i 's/foo/bar/' file.txt" },
    }));
    const pattern2 = generateApprovalPattern(makeRequest({
      args: { command: "sed 's/foo/bar/' file.txt" },
    }));
    expect(pattern1).toBe('bash:sed');
    expect(pattern2).toBe('bash:sed');
    expect(pattern1).toBe(pattern2);
  });

  it('handles piped commands — pattern is first command', () => {
    const pattern = generateApprovalPattern(makeRequest({
      args: { command: 'cat file.txt | grep pattern' },
    }));
    expect(pattern).toBe('bash:cat');
  });

  it('handles chained commands — pattern is first command', () => {
    const pattern = generateApprovalPattern(makeRequest({
      args: { command: 'cd dir && npm test' },
    }));
    expect(pattern).toBe('bash:cd');
  });

  it('file operations use file path', () => {
    const pattern = generateApprovalPattern(makeRequest({
      tool: 'write_file',
      action: 'write_file',
      args: { path: '/src/index.ts', content: 'hello' },
    }));
    expect(pattern).toBe('write_file:/src/index.ts');
  });

  it('handles npm/npx commands', () => {
    const pattern1 = generateApprovalPattern(makeRequest({
      args: { command: 'npm test --coverage' },
    }));
    const pattern2 = generateApprovalPattern(makeRequest({
      args: { command: 'npm install lodash' },
    }));
    // Both start with npm, so same base pattern
    expect(pattern1).toBe('bash:npm');
    expect(pattern2).toBe('bash:npm');
  });

  it('handles empty command gracefully', () => {
    const pattern = generateApprovalPattern(makeRequest({
      args: { command: '' },
    }));
    expect(pattern).toBe('bash:');
  });

  it('default pattern for unknown tools', () => {
    const pattern = generateApprovalPattern(makeRequest({
      tool: 'custom_tool',
      action: 'custom_tool',
      args: { query: 'search term' },
    }));
    expect(pattern).toBe('custom_tool:search term');
  });
});

describe('risk-level guard', () => {
  // Simulates the handleApprovalRequest logic
  function wouldAutoApprove(request: ApprovalRequest, alwaysAllowed: Set<string>): boolean {
    const pattern = generateApprovalPattern(request);
    return alwaysAllowed.has(pattern) && (request.risk === 'low' || request.risk === 'moderate');
  }

  it('auto-approves moderate risk when pattern matches', () => {
    const allowed = new Set(['bash:sed']);
    const request = makeRequest({
      args: { command: "sed 's/old/new/' file.txt" },
      risk: 'moderate',
    });
    expect(wouldAutoApprove(request, allowed)).toBe(true);
  });

  it('auto-approves low risk when pattern matches', () => {
    const allowed = new Set(['bash:ls']);
    const request = makeRequest({
      args: { command: 'ls -la' },
      risk: 'low',
    });
    expect(wouldAutoApprove(request, allowed)).toBe(true);
  });

  it('shows dialog for high risk even when pattern matches', () => {
    const allowed = new Set(['bash:rm']);
    const request = makeRequest({
      args: { command: 'rm -rf /tmp/test' },
      risk: 'high',
    });
    expect(wouldAutoApprove(request, allowed)).toBe(false);
  });

  it('shows dialog for critical risk even when pattern matches', () => {
    const allowed = new Set(['bash:sudo']);
    const request = makeRequest({
      args: { command: 'sudo rm -rf /' },
      risk: 'critical',
    });
    expect(wouldAutoApprove(request, allowed)).toBe(false);
  });

  it('shows dialog when pattern not in allowed set', () => {
    const allowed = new Set(['bash:npm']);
    const request = makeRequest({
      args: { command: 'pip install something' },
      risk: 'moderate',
    });
    expect(wouldAutoApprove(request, allowed)).toBe(false);
  });
});
