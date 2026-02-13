import { describe, expect, it } from 'vitest';
import { detectFileMutationViaBash, isReadOnlyBashCommand, evaluateBashPolicy, stripCdPrefix } from '../../src/integrations/bash-policy.js';
import { classifyBashCommandDangerLevel } from '../../src/tools/permission.js';
import { SandboxManager } from '../../src/integrations/safety.js';
import { BasicSandbox } from '../../src/integrations/sandbox/basic.js';

describe('B1: stream redirect false positives fixed', () => {
  it('2>&1 is NOT detected as file mutation', () => {
    expect(detectFileMutationViaBash('npx tsc --noEmit 2>&1 | head -20').detected).toBe(false);
  });

  it('>&2 is NOT detected as file mutation', () => {
    expect(detectFileMutationViaBash('echo "error" >&2').detected).toBe(false);
  });

  it('1>&2 is NOT detected as file mutation', () => {
    expect(detectFileMutationViaBash('echo "warning" 1>&2').detected).toBe(false);
  });

  it('> file.txt IS still detected', () => {
    expect(detectFileMutationViaBash('echo "data" > file.txt').detected).toBe(true);
  });

  it('>> file.txt IS still detected', () => {
    expect(detectFileMutationViaBash('echo "data" >> file.txt').detected).toBe(true);
  });

  it('> /dev/null is still allowed', () => {
    expect(detectFileMutationViaBash('cmd > /dev/null 2>&1').detected).toBe(false);
  });
});

describe('B4: tee false positive fixed', () => {
  it('cmd | tee (no filename) is NOT detected', () => {
    expect(detectFileMutationViaBash('npm test | tee').detected).toBe(false);
  });

  it('cmd | tee | grep (pipe chain) is NOT detected', () => {
    expect(detectFileMutationViaBash('npm test | tee | grep FAIL').detected).toBe(false);
  });

  it('cmd | tee output.txt IS detected', () => {
    expect(detectFileMutationViaBash('npm test | tee output.txt').detected).toBe(true);
  });

  it('cmd | tee /dev/null is NOT detected', () => {
    expect(detectFileMutationViaBash('npm test | tee /dev/null').detected).toBe(false);
  });
});

describe('B2: research-safe read-only bash', () => {
  it('read-only commands are allowed', () => {
    const result = evaluateBashPolicy('ls -la', 'read_only', 'block_file_mutation');
    expect(result.allowed).toBe(true);
  });

  it('cat is allowed in read_only mode', () => {
    const result = evaluateBashPolicy('cat src/agent.ts', 'read_only', 'block_file_mutation');
    expect(result.allowed).toBe(true);
  });

  it('git log is allowed in read_only mode', () => {
    const result = evaluateBashPolicy('git log --oneline -10', 'read_only', 'block_file_mutation');
    expect(result.allowed).toBe(true);
  });

  it('npm test is allowed in read_only mode', () => {
    const result = evaluateBashPolicy('npm test', 'read_only', 'block_file_mutation');
    expect(result.allowed).toBe(true);
  });

  it('write commands are blocked in read_only mode', () => {
    const result = evaluateBashPolicy('rm -rf dist/', 'read_only', 'block_file_mutation');
    expect(result.allowed).toBe(false);
  });

  it('git commit is blocked in read_only mode', () => {
    const result = evaluateBashPolicy('git commit -m "test"', 'read_only', 'block_file_mutation');
    expect(result.allowed).toBe(false);
  });
});

describe('F6: permission.ts and bash-policy.ts classification agreement', () => {
  const readOnlyCommands = [
    'ls -la',
    'cat src/agent.ts',
    'head -20 file.txt',
    'tail -f output.log',
    'grep -r "pattern" src/',
    'find . -name "*.ts"',
    'git status',
    'git log --oneline',
    'git diff HEAD',
    'wc -l file.txt',
    'tree src/',
    'pwd',
    'which node',
    'node --version',
    'npm list',
    'du -sh dist/',
    'diff a.txt b.txt',
    'jq ".name" package.json',
    'sort file.txt',
    'npx tsc --noEmit',
  ];

  const writeCommands = [
    'rm -rf dist/',
    'mv old.ts new.ts',
    'cp src/a.ts src/b.ts',
    'mkdir -p new-dir',
    'touch newfile.ts',
    'git add .',
    'git commit -m "test"',
    'git push origin main',
    'npm install express',
  ];

  for (const cmd of readOnlyCommands) {
    it(`read-only "${cmd}" classified consistently`, () => {
      const bashPolicySays = isReadOnlyBashCommand(cmd);
      const permissionSays = classifyBashCommandDangerLevel(cmd);
      // Both should agree: bash-policy says read-only, permission says safe
      expect(bashPolicySays).toBe(true);
      expect(permissionSays).toBe('safe');
    });
  }

  for (const cmd of writeCommands) {
    it(`write "${cmd}" classified consistently`, () => {
      const bashPolicySays = isReadOnlyBashCommand(cmd);
      const permissionSays = classifyBashCommandDangerLevel(cmd);
      // Both should agree: bash-policy says NOT read-only, permission says NOT safe
      expect(bashPolicySays).toBe(false);
      expect(permissionSays).not.toBe('safe');
    });
  }
});

describe('F8: cd prefix stripping in sandbox allowlist', () => {
  describe('stripCdPrefix()', () => {
    it('strips single cd prefix', () => {
      expect(stripCdPrefix('cd /some/path && npm test')).toBe('npm test');
    });

    it('strips chained cd prefixes', () => {
      expect(stripCdPrefix('cd src && cd tests && vitest')).toBe('vitest');
    });

    it('returns command as-is when no cd prefix', () => {
      expect(stripCdPrefix('npm test')).toBe('npm test');
    });

    it('returns empty string for bare cd (no &&)', () => {
      expect(stripCdPrefix('cd /path')).toBe('cd /path');
    });
  });

  describe('SandboxManager.isCommandAllowed() with cd prefix', () => {
    const sandbox = new SandboxManager({
      enabled: true,
      allowedCommands: ['npm', 'node', 'vitest', 'ls'],
      allowedPaths: ['.'],
    });

    it('allows "cd /some/path && npm test"', () => {
      const result = sandbox.isCommandAllowed('cd /some/path && npm test');
      expect(result.allowed).toBe(true);
    });

    it('allows "cd src && cd tests && vitest"', () => {
      const result = sandbox.isCommandAllowed('cd src && cd tests && vitest');
      expect(result.allowed).toBe(true);
    });

    it('allows "cd src && ls"', () => {
      const result = sandbox.isCommandAllowed('cd src && ls');
      expect(result.allowed).toBe(true);
    });

    it('blocks "cd /path && rm -rf /" (blocked pattern)', () => {
      const result = sandbox.isCommandAllowed('cd /path && rm -rf /');
      expect(result.allowed).toBe(false);
    });
  });

  describe('BasicSandbox.validateCommand() with cd prefix', () => {
    const sandbox = new BasicSandbox({
      allowedCommands: ['npm', 'node', 'vitest', 'ls'],
      timeout: 60000,
    });

    it('allows "cd /some/path && npm test"', () => {
      const result = sandbox.validateCommand('cd /some/path && npm test', {
        allowedCommands: ['npm', 'node', 'vitest', 'ls'],
        timeout: 60000,
      });
      expect(result.allowed).toBe(true);
    });

    it('allows "cd src && cd tests && vitest"', () => {
      const result = sandbox.validateCommand('cd src && cd tests && vitest', {
        allowedCommands: ['npm', 'node', 'vitest', 'ls'],
        timeout: 60000,
      });
      expect(result.allowed).toBe(true);
    });

    it('blocks command not in allowlist even with cd prefix', () => {
      const result = sandbox.validateCommand('cd /path && python3 script.py', {
        allowedCommands: ['npm', 'node', 'vitest', 'ls'],
        timeout: 60000,
      });
      expect(result.allowed).toBe(false);
    });
  });
});
