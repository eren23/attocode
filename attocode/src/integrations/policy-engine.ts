/**
 * Unified policy engine.
 *
 * Resolves effective tool/bash/approval behavior from profiles plus
 * compatibility mappings from legacy config fields.
 */

import type { PolicyEngineConfig, PolicyProfile, SandboxConfig } from '../types.js';
import type { SwarmConfig, SwarmWorkerSpec } from './swarm/types.js';
import { evaluateBashPolicy } from './bash-policy.js';

export const DEFAULT_POLICY_PROFILES: Record<string, PolicyProfile> = {
  'research-safe': {
    toolAccessMode: 'whitelist',
    allowedTools: ['read_file', 'list_files', 'glob', 'grep'],
    deniedTools: ['write_file', 'edit_file', 'delete_file', 'bash'],
    bashMode: 'disabled',
    bashWriteProtection: 'block_file_mutation',
  },
  'code-strict-bash': {
    toolAccessMode: 'whitelist',
    allowedTools: ['read_file', 'write_file', 'edit_file', 'list_files', 'glob', 'grep', 'bash'],
    bashMode: 'read_only',
    bashWriteProtection: 'block_file_mutation',
  },
  'code-full': {
    toolAccessMode: 'all',
    bashMode: 'full',
    bashWriteProtection: 'off',
  },
  'review-safe': {
    toolAccessMode: 'whitelist',
    allowedTools: ['read_file', 'list_files', 'glob', 'grep'],
    deniedTools: ['write_file', 'edit_file', 'delete_file', 'bash'],
    bashMode: 'disabled',
    bashWriteProtection: 'block_file_mutation',
  },
};

export const DEFAULT_POLICY_ENGINE_CONFIG: Required<
  Pick<PolicyEngineConfig, 'enabled' | 'legacyFallback' | 'defaultProfile' | 'defaultSwarmProfile'>
> = {
  enabled: true,
  legacyFallback: true,
  defaultProfile: 'code-full',
  defaultSwarmProfile: 'code-strict-bash',
};

export interface ResolvePolicyProfileOptions {
  policyEngine?: PolicyEngineConfig | false;
  requestedProfile?: string;
  swarmConfig?: SwarmConfig;
  worker?: SwarmWorkerSpec;
  taskType?: string;
  sandboxConfig?: SandboxConfig;
  isSwarmWorker?: boolean;
  legacyAllowedTools?: string[];
  legacyDeniedTools?: string[];
  globalDeniedTools?: string[];
}

export interface ResolvedPolicyProfile {
  profileName: string;
  profile: PolicyProfile;
  metadata: {
    selectionSource: 'explicit' | 'worker-capability' | 'task-type' | 'default';
    usedLegacyMappings: boolean;
    legacyMappingSources: string[];
    warnings: string[];
  };
}

function mergeProfiles(...profiles: Array<PolicyProfile | undefined>): PolicyProfile {
  const merged: PolicyProfile = {};
  for (const p of profiles) {
    if (!p) continue;
    merged.toolAccessMode = p.toolAccessMode ?? merged.toolAccessMode;
    merged.allowedTools = p.allowedTools ?? merged.allowedTools;
    merged.deniedTools = p.deniedTools ?? merged.deniedTools;
    merged.bashMode = p.bashMode ?? merged.bashMode;
    merged.bashWriteProtection = p.bashWriteProtection ?? merged.bashWriteProtection;
    if (p.approval) {
      merged.approval = {
        autoApprove: p.approval.autoApprove ?? merged.approval?.autoApprove,
        scopedApprove: p.approval.scopedApprove ?? merged.approval?.scopedApprove,
        requireApproval: p.approval.requireApproval ?? merged.approval?.requireApproval,
      };
    }
  }
  return merged;
}

function inferSwarmProfileForTask(taskType?: string): string {
  if (!taskType) return 'code-strict-bash';
  if (['research', 'analysis', 'review', 'merge'].includes(taskType)) {
    return 'research-safe';
  }
  if (['design', 'document'].includes(taskType)) {
    return 'code-strict-bash';
  }
  return 'code-strict-bash';
}

function inferSwarmProfileForWorker(worker?: SwarmWorkerSpec): string | undefined {
  if (!worker?.capabilities || worker.capabilities.length === 0) return undefined;
  const caps = new Set(worker.capabilities);

  if (caps.has('code') || caps.has('write') || caps.has('test') || caps.has('document')) {
    return 'code-strict-bash';
  }
  if (caps.has('review')) {
    return 'review-safe';
  }
  if (caps.has('research')) {
    return 'research-safe';
  }
  return undefined;
}

function applyLegacyMappings(
  profile: PolicyProfile,
  options: ResolvePolicyProfileOptions,
): {
  profile: PolicyProfile;
  metadata: ResolvedPolicyProfile['metadata'];
} {
  const merged = { ...profile };
  const metadata: ResolvedPolicyProfile['metadata'] = {
    selectionSource: 'default',
    usedLegacyMappings: false,
    legacyMappingSources: [],
    warnings: [],
  };

  const legacyAllowed = options.legacyAllowedTools ?? options.worker?.allowedTools;
  if (legacyAllowed && legacyAllowed.length > 0) {
    merged.toolAccessMode = 'whitelist';
    merged.allowedTools = [...legacyAllowed];
    metadata.usedLegacyMappings = true;
    metadata.legacyMappingSources.push('legacyAllowedTools');
    metadata.warnings.push(
      'Legacy tool whitelist is active. Migrate to policyProfiles + worker.policyProfile.',
    );
  }

  const denied = [
    ...(merged.deniedTools ?? []),
    ...(options.legacyDeniedTools ?? options.worker?.deniedTools ?? []),
    ...(options.globalDeniedTools ?? options.swarmConfig?.globalDeniedTools ?? []),
  ];
  if (denied.length > 0) {
    merged.deniedTools = [...new Set(denied)];
    metadata.usedLegacyMappings = true;
    metadata.legacyMappingSources.push('legacyDeniedTools/globalDeniedTools');
    metadata.warnings.push(
      'Legacy denied tools are active. Migrate to policyProfiles[].deniedTools.',
    );
  }

  if (options.sandboxConfig?.blockFileCreationViaBash) {
    merged.bashWriteProtection = 'block_file_mutation';
    metadata.usedLegacyMappings = true;
    metadata.legacyMappingSources.push('sandbox.blockFileCreationViaBash');
    metadata.warnings.push(
      'sandbox.blockFileCreationViaBash is legacy compatibility behavior. Use policy profile bashWriteProtection.',
    );
  }
  if (options.sandboxConfig?.bashMode) {
    merged.bashMode = options.sandboxConfig.bashMode;
    metadata.usedLegacyMappings = true;
    metadata.legacyMappingSources.push('sandbox.bashMode');
    metadata.warnings.push(
      'sandbox.bashMode override is active. Prefer profile-level bashMode.',
    );
  }
  if (options.sandboxConfig?.bashWriteProtection) {
    merged.bashWriteProtection = options.sandboxConfig.bashWriteProtection;
    metadata.usedLegacyMappings = true;
    metadata.legacyMappingSources.push('sandbox.bashWriteProtection');
    metadata.warnings.push(
      'sandbox.bashWriteProtection override is active. Prefer profile-level bashWriteProtection.',
    );
  }

  return { profile: merged, metadata };
}

export function resolvePolicyProfile(options: ResolvePolicyProfileOptions): ResolvedPolicyProfile {
  const policyEngine = options.policyEngine || undefined;
  const legacyFallback = policyEngine?.legacyFallback ?? DEFAULT_POLICY_ENGINE_CONFIG.legacyFallback;
  const mergedProfiles: Record<string, PolicyProfile> = {
    ...DEFAULT_POLICY_PROFILES,
    ...(policyEngine?.profiles ?? {}),
    ...(options.swarmConfig?.policyProfiles ?? {}),
  };

  const defaultProfileName = options.isSwarmWorker
    ? (policyEngine?.defaultSwarmProfile ?? DEFAULT_POLICY_ENGINE_CONFIG.defaultSwarmProfile)
    : (policyEngine?.defaultProfile ?? DEFAULT_POLICY_ENGINE_CONFIG.defaultProfile);

  let selectionSource: ResolvedPolicyProfile['metadata']['selectionSource'] = 'default';
  let requestedProfile: string = defaultProfileName;

  if (options.requestedProfile || options.worker?.policyProfile) {
    requestedProfile = options.requestedProfile ?? options.worker?.policyProfile ?? defaultProfileName;
    selectionSource = 'explicit';
  } else if (options.isSwarmWorker) {
    const workerInferred = inferSwarmProfileForWorker(options.worker);
    if (workerInferred) {
      requestedProfile = workerInferred;
      selectionSource = 'worker-capability';
    } else if (options.taskType) {
      requestedProfile = inferSwarmProfileForTask(options.taskType);
      selectionSource = 'task-type';
    } else {
      requestedProfile = defaultProfileName;
      selectionSource = 'default';
    }
  }

  const base = mergedProfiles[defaultProfileName] ?? DEFAULT_POLICY_PROFILES['code-full'];
  const requested = mergedProfiles[requestedProfile] ?? base;

  const merged = mergeProfiles(base, requested);
  const { profile: effective, metadata } = legacyFallback
    ? applyLegacyMappings(merged, options)
    : {
        profile: merged,
        metadata: {
          selectionSource: 'default' as const,
          usedLegacyMappings: false,
          legacyMappingSources: [],
          warnings: [],
        },
      };

  return {
    profileName: requestedProfile,
    profile: effective,
    metadata: {
      ...metadata,
      selectionSource,
    },
  };
}

export function isToolAllowedByProfile(
  toolName: string,
  profile: PolicyProfile,
): { allowed: boolean; reason?: string } {
  const mode = profile.toolAccessMode ?? 'all';

  if (mode === 'whitelist') {
    const allowed = profile.allowedTools ?? [];
    if (!allowed.includes(toolName)) {
      return { allowed: false, reason: `Tool '${toolName}' is not allowed by policy whitelist.` };
    }
  }

  if ((profile.deniedTools ?? []).includes(toolName)) {
    return { allowed: false, reason: `Tool '${toolName}' is denied by policy profile.` };
  }

  return { allowed: true };
}

export function evaluateBashCommandByProfile(
  command: string,
  profile: PolicyProfile,
  taskType?: string,
): { allowed: boolean; reason?: string } {
  let mode = profile.bashMode ?? 'full';
  if (mode === 'task_scoped') {
    mode = ['implement', 'test', 'refactor', 'integrate', 'deploy', 'document'].includes(taskType ?? '')
      ? 'read_only'
      : 'disabled';
  }

  const decision = evaluateBashPolicy(
    command,
    mode,
    profile.bashWriteProtection ?? 'off',
  );

  return { allowed: decision.allowed, reason: decision.reason };
}

export function mergeApprovalScopeWithProfile(
  scope: {
    autoApprove: string[];
    scopedApprove: Record<string, { paths: string[] }>;
    requireApproval: string[];
  },
  profile: PolicyProfile,
): {
  autoApprove: string[];
  scopedApprove: Record<string, { paths: string[] }>;
  requireApproval: string[];
} {
  return {
    autoApprove: [...new Set([...(scope.autoApprove ?? []), ...(profile.approval?.autoApprove ?? [])])],
    scopedApprove: { ...(scope.scopedApprove ?? {}), ...(profile.approval?.scopedApprove ?? {}) },
    requireApproval: [...new Set([...(scope.requireApproval ?? []), ...(profile.approval?.requireApproval ?? [])])],
  };
}
