import { describe, expect, it } from 'vitest';
import { isToolAllowedByProfile, resolvePolicyProfile } from '../../src/integrations/policy-engine.js';
import type { SwarmWorkerSpec } from '../../src/integrations/swarm/types.js';

describe('resolvePolicyProfile (swarm inference)', () => {
  it('uses code-strict-bash for coder design tasks by worker capability', () => {
    const worker: SwarmWorkerSpec = {
      name: 'coder',
      model: 'test/model',
      capabilities: ['code'],
    };

    const resolved = resolvePolicyProfile({
      isSwarmWorker: true,
      worker,
      taskType: 'design',
    });

    expect(resolved.profileName).toBe('code-strict-bash');
    expect(resolved.metadata.selectionSource).toBe('worker-capability');
    expect(isToolAllowedByProfile('write_file', resolved.profile).allowed).toBe(true);
  });

  it('keeps research-safe for researcher design tasks by worker capability', () => {
    const worker: SwarmWorkerSpec = {
      name: 'researcher',
      model: 'test/model',
      capabilities: ['research'],
    };

    const resolved = resolvePolicyProfile({
      isSwarmWorker: true,
      worker,
      taskType: 'design',
    });

    expect(resolved.profileName).toBe('research-safe');
    expect(resolved.metadata.selectionSource).toBe('worker-capability');
    expect(isToolAllowedByProfile('write_file', resolved.profile).allowed).toBe(false);
  });

  it('uses task-type fallback when no worker capability is available', () => {
    const resolved = resolvePolicyProfile({
      isSwarmWorker: true,
      taskType: 'design',
    });

    expect(resolved.profileName).toBe('code-strict-bash');
    expect(resolved.metadata.selectionSource).toBe('task-type');
  });

  it('explicit requested profile overrides capability/task inference', () => {
    const worker: SwarmWorkerSpec = {
      name: 'coder',
      model: 'test/model',
      capabilities: ['code'],
    };

    const resolved = resolvePolicyProfile({
      isSwarmWorker: true,
      requestedProfile: 'research-safe',
      worker,
      taskType: 'implement',
    });

    expect(resolved.profileName).toBe('research-safe');
    expect(resolved.metadata.selectionSource).toBe('explicit');
    expect(isToolAllowedByProfile('write_file', resolved.profile).allowed).toBe(false);
  });
});

