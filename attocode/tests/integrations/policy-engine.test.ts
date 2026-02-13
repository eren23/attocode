import { describe, expect, it } from 'vitest';
import { isToolAllowedByProfile, resolvePolicyProfile, DEFAULT_POLICY_PROFILES } from '../../src/integrations/policy-engine.js';
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
    // research-safe now includes write_file so research workers can save findings
    expect(isToolAllowedByProfile('write_file', resolved.profile).allowed).toBe(true);
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
    // B2: research-safe now includes write_file AND bash (read_only mode, not disabled)
    expect(isToolAllowedByProfile('write_file', resolved.profile).allowed).toBe(true);
    expect(isToolAllowedByProfile('bash', resolved.profile).allowed).toBe(true);
  });
});

describe('web_search in default profiles', () => {
  it('research-safe includes web_search', () => {
    expect(DEFAULT_POLICY_PROFILES['research-safe'].allowedTools).toContain('web_search');
  });

  it('review-safe includes web_search', () => {
    expect(DEFAULT_POLICY_PROFILES['review-safe'].allowedTools).toContain('web_search');
  });

  it('research worker can use web_search', () => {
    const resolved = resolvePolicyProfile({
      isSwarmWorker: true,
      worker: { name: 'researcher', model: 'test/model', capabilities: ['research'] },
    });
    expect(isToolAllowedByProfile('web_search', resolved.profile).allowed).toBe(true);
  });
});

describe('profileExtensions (YAML-level profile patching)', () => {
  it('addTools extends an existing profile allowedTools', () => {
    const resolved = resolvePolicyProfile({
      isSwarmWorker: true,
      worker: { name: 'researcher', model: 'test/model', capabilities: ['research'] },
      swarmConfig: {
        profileExtensions: {
          'research-safe': { addTools: ['custom_tool', 'another_tool'] },
        },
      } as any,
    });
    expect(isToolAllowedByProfile('custom_tool', resolved.profile).allowed).toBe(true);
    expect(isToolAllowedByProfile('another_tool', resolved.profile).allowed).toBe(true);
    // Original tools still present
    expect(isToolAllowedByProfile('read_file', resolved.profile).allowed).toBe(true);
  });

  it('removeTools removes from allowedTools and adds to deniedTools', () => {
    const resolved = resolvePolicyProfile({
      isSwarmWorker: true,
      worker: { name: 'researcher', model: 'test/model', capabilities: ['research'] },
      swarmConfig: {
        profileExtensions: {
          'research-safe': { removeTools: ['grep'] },
        },
      } as any,
    });
    expect(isToolAllowedByProfile('grep', resolved.profile).allowed).toBe(false);
    // Other tools unaffected
    expect(isToolAllowedByProfile('read_file', resolved.profile).allowed).toBe(true);
  });

  it('addTools and removeTools can be combined', () => {
    const resolved = resolvePolicyProfile({
      isSwarmWorker: true,
      worker: { name: 'researcher', model: 'test/model', capabilities: ['research'] },
      swarmConfig: {
        profileExtensions: {
          'research-safe': { addTools: ['custom_tool'], removeTools: ['list_files'] },
        },
      } as any,
    });
    expect(isToolAllowedByProfile('custom_tool', resolved.profile).allowed).toBe(true);
    expect(isToolAllowedByProfile('list_files', resolved.profile).allowed).toBe(false);
  });

  it('ignores extensions for non-existent profiles', () => {
    const resolved = resolvePolicyProfile({
      isSwarmWorker: true,
      worker: { name: 'researcher', model: 'test/model', capabilities: ['research'] },
      swarmConfig: {
        profileExtensions: {
          'nonexistent-profile': { addTools: ['bash'] },
        },
      } as any,
    });
    // Should resolve normally without errors
    expect(resolved.profileName).toBe('research-safe');
  });
});

describe('worker extraTools (per-worker additive merge)', () => {
  it('merges extraTools into resolved whitelist profile', () => {
    const resolved = resolvePolicyProfile({
      isSwarmWorker: true,
      worker: {
        name: 'researcher',
        model: 'test/model',
        capabilities: ['research'],
        extraTools: ['custom_mcp_tool'],
      },
    });
    expect(isToolAllowedByProfile('custom_mcp_tool', resolved.profile).allowed).toBe(true);
    // Original tools still present
    expect(isToolAllowedByProfile('read_file', resolved.profile).allowed).toBe(true);
  });

  it('extraTools overrides deniedTools (B3)', () => {
    // B3: extraTools now removes from deniedTools so the tool actually works.
    // Also, B2: bash is no longer in research-safe deniedTools at all.
    const resolved = resolvePolicyProfile({
      isSwarmWorker: true,
      worker: {
        name: 'researcher',
        model: 'test/model',
        capabilities: ['research'],
        extraTools: ['delete_file'], // delete_file IS in research-safe deniedTools
      },
    });
    expect(resolved.profile.allowedTools).toContain('delete_file');
    // B3: extraTools now removes from deniedTools, so tool is allowed
    expect(isToolAllowedByProfile('delete_file', resolved.profile).allowed).toBe(true);
  });
});

describe('B2: research-safe bash access', () => {
  it('research-safe profile has read_only bashMode', () => {
    expect(DEFAULT_POLICY_PROFILES['research-safe'].bashMode).toBe('read_only');
  });

  it('research-safe profile includes bash in allowedTools', () => {
    expect(DEFAULT_POLICY_PROFILES['research-safe'].allowedTools).toContain('bash');
  });

  it('research-safe profile does not deny bash', () => {
    expect(DEFAULT_POLICY_PROFILES['research-safe'].deniedTools).not.toContain('bash');
  });

  it('research worker can use bash', () => {
    const resolved = resolvePolicyProfile({
      isSwarmWorker: true,
      worker: { name: 'researcher', model: 'test/model', capabilities: ['research'] },
    });
    expect(isToolAllowedByProfile('bash', resolved.profile).allowed).toBe(true);
  });
});

