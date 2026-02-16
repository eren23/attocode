import { afterEach, describe, expect, it } from 'vitest';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { HookManager } from '../../src/integrations/utilities/hooks.js';
import type { HooksConfig, PluginsConfig } from '../../src/types.js';

async function createTempDir(): Promise<string> {
  return mkdtemp(join(tmpdir(), 'attocode-hooks-shell-'));
}

describe('HookManager shell hooks', () => {
  const tempDirs: string[] = [];

  afterEach(async () => {
    for (const dir of tempDirs.splice(0)) {
      await rm(dir, { recursive: true, force: true });
    }
  });

  it('executes configured shell hook and passes JSON payload on stdin', async () => {
    const dir = await createTempDir();
    tempDirs.push(dir);
    const outputFile = join(dir, 'payload.json');

    const hooksConfig: HooksConfig = {
      enabled: true,
      builtIn: {},
      custom: [],
      shell: {
        enabled: true,
        defaultTimeoutMs: 2000,
        commands: [
          {
            event: 'run.before',
            command: process.execPath,
            args: [
              '-e',
              "const fs=require('fs');let d='';process.stdin.on('data',c=>d+=c);process.stdin.on('end',()=>fs.writeFileSync(process.argv[1],d));",
              outputFile,
            ],
          },
        ],
      },
    };
    const pluginsConfig: PluginsConfig = { enabled: true, plugins: [], discoveryPaths: [] };
    const manager = new HookManager(hooksConfig, pluginsConfig);

    await manager.emitAsync({ type: 'run.before', task: 'test task' });

    const saved = JSON.parse(await readFile(outputFile, 'utf-8'));
    expect(saved.event).toBe('run.before');
    expect(saved.payload).toEqual({ type: 'run.before', task: 'test task' });
  });

  it('respects envAllowlist for shell hooks', async () => {
    const dir = await createTempDir();
    tempDirs.push(dir);
    const outputFile = join(dir, 'env.json');

    process.env.ATTOCODE_HOOK_TEST_ALLOWED = 'yes';
    process.env.ATTOCODE_HOOK_TEST_BLOCKED = 'no';

    const hooksConfig: HooksConfig = {
      enabled: true,
      builtIn: {},
      custom: [],
      shell: {
        enabled: true,
        envAllowlist: ['ATTOCODE_HOOK_TEST_ALLOWED'],
        commands: [
          {
            event: 'completion.before',
            command: process.execPath,
            args: [
              '-e',
              "const fs=require('fs');const body={allowed:process.env.ATTOCODE_HOOK_TEST_ALLOWED||null,blocked:process.env.ATTOCODE_HOOK_TEST_BLOCKED||null};fs.writeFileSync(process.argv[1],JSON.stringify(body));",
              outputFile,
            ],
          },
        ],
      },
    };
    const manager = new HookManager(hooksConfig, { enabled: true, plugins: [], discoveryPaths: [] });

    await manager.emitAsync({ type: 'completion.before', reason: 'future_intent' });

    const data = JSON.parse(await readFile(outputFile, 'utf-8'));
    expect(data.allowed).toBe('yes');
    expect(data.blocked).toBeNull();
  });

  it('does not throw when shell hook times out', async () => {
    const hooksConfig: HooksConfig = {
      enabled: true,
      builtIn: {},
      custom: [],
      shell: {
        enabled: true,
        defaultTimeoutMs: 50,
        commands: [
          {
            event: 'recovery.before',
            command: process.execPath,
            args: ['-e', 'setTimeout(()=>{}, 2000)'],
          },
        ],
      },
    };
    const manager = new HookManager(hooksConfig, { enabled: true, plugins: [], discoveryPaths: [] });

    await expect(
      manager.emitAsync({ type: 'recovery.before', reason: 'future_intent', attempt: 1, maxAttempts: 2 }),
    ).resolves.toBeUndefined();
  });
});
