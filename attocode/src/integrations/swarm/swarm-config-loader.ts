/**
 * Swarm Config Loader
 *
 * YAML parser + config loader + merge logic for swarm.yaml files.
 * Supports nested objects, block arrays, multiline strings, and type coercion.
 *
 * Search order:
 *   1. {cwd}/.attocode/swarm.yaml
 *   2. {cwd}/.attocode/swarm.yml
 *   3. {cwd}/.attocode/swarm.json (fallback)
 *   4. {homedir}/.attocode/swarm.yaml
 *   5. null if none found
 *
 * Merge order: DEFAULT < yaml < CLI overrides
 */

import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { homedir } from 'node:os';
import type { SwarmConfig, SwarmWorkerSpec, WorkerCapability } from './types.js';
import { DEFAULT_SWARM_CONFIG } from './types.js';

// ─── YAML Types ─────────────────────────────────────────────────────────────

/** Raw parsed YAML — untyped nested structure */
export type SwarmYamlConfig = Record<string, unknown>;

// ─── YAML Parser ────────────────────────────────────────────────────────────

/**
 * Parse a simple YAML string into a nested object.
 *
 * Supports:
 * - Key-value pairs (key: value)
 * - Nested objects via indentation (2-space indent)
 * - Block arrays (- item, including objects within arrays)
 * - Multiline strings (| indicator)
 * - Type coercion (bool, number, null)
 * - Comments (# ...) and blank lines
 *
 * NOT a general-purpose YAML parser — handles the swarm.yaml schema.
 */
export function parseSwarmYaml(content: string): SwarmYamlConfig {
  const lines = content.split('\n');
  const result: SwarmYamlConfig = {};
  const stack: Array<{ indent: number; obj: Record<string, unknown> }> = [
    { indent: -1, obj: result },
  ];
  let multilineKey: string | null = null;
  let multilineIndent = 0;
  let multilineLines: string[] = [];
  let multilineTarget: Record<string, unknown> = result;

  // State for array parsing
  let arrayKey: string | null = null;
  let arrayTarget: Record<string, unknown> = result;
  let currentArrayItem: Record<string, unknown> | null = null;
  let arrayItemIndent = 0;

  for (let i = 0; i < lines.length; i++) {
    const rawLine = lines[i];

    // Handle multiline string continuation
    if (multilineKey !== null) {
      const stripped = rawLine.replace(/\s+$/, '');
      if (stripped === '' || getIndent(rawLine) > multilineIndent) {
        // Part of the multiline block
        const textContent = rawLine.slice(Math.min(multilineIndent + 2, rawLine.length));
        multilineLines.push(textContent);
        continue;
      } else {
        // End of multiline block
        multilineTarget[multilineKey] = multilineLines.join('\n').replace(/\n+$/, '');
        multilineKey = null;
        multilineLines = [];
        // Fall through to process this line normally
      }
    }

    // Skip blank lines and comments
    const trimmed = rawLine.trim();
    if (trimmed === '' || trimmed.startsWith('#')) continue;

    const indent = getIndent(rawLine);

    // Strip inline comments (but not inside quoted strings)
    const commentFree = stripInlineComment(trimmed);

    // Handle array items (- value or - key: value)
    if (commentFree.startsWith('- ')) {
      const itemContent = commentFree.slice(2).trim();

      if (arrayKey === null) {
        // Array without a preceding key — skip
        continue;
      }

      // If itemContent contains a colon, it's an object in array
      if (itemContent.includes(':')) {
        // Start of new array object item
        if (currentArrayItem && arrayKey) {
          // Push previous item
          pushToArray(arrayTarget, arrayKey, currentArrayItem);
        }
        currentArrayItem = {};
        arrayItemIndent = indent;
        const [key, val] = splitKeyValue(itemContent);
        if (key) {
          currentArrayItem[key] = coerceValue(val);
        }
        continue;
      }

      // Simple array item (scalar)
      if (arrayKey) {
        pushToArray(arrayTarget, arrayKey, coerceValue(itemContent));
        continue;
      }
      continue;
    }

    // If we're in an array item and this line is indented deeper, it's a property
    if (currentArrayItem && indent > arrayItemIndent) {
      const [key, val] = splitKeyValue(commentFree);
      if (key) {
        if (val === '|') {
          // Multiline string within array item
          multilineKey = key;
          multilineIndent = indent;
          multilineLines = [];
          multilineTarget = currentArrayItem;
        } else {
          currentArrayItem[key] = coerceValue(val);
        }
      }
      continue;
    }

    // End of array item section — flush
    if (currentArrayItem && arrayKey) {
      pushToArray(arrayTarget, arrayKey, currentArrayItem);
      currentArrayItem = null;
    }

    // Regular key: value line
    if (commentFree.includes(':')) {
      const [key, val] = splitKeyValue(commentFree);
      if (!key) continue;

      // Pop stack to find correct parent
      while (stack.length > 1 && stack[stack.length - 1].indent >= indent) {
        stack.pop();
      }
      const parent = stack[stack.length - 1].obj;

      if (val === '' || val === undefined) {
        // Nested object or array — check next non-blank line
        const nextContent = peekNextContent(lines, i + 1);
        if (nextContent && nextContent.trimmed.startsWith('- ')) {
          // It's an array
          parent[key] = [];
          arrayKey = key;
          arrayTarget = parent;
          arrayItemIndent = getIndent(nextContent.raw);
        } else {
          // It's a nested object
          const child: Record<string, unknown> = {};
          parent[key] = child;
          stack.push({ indent, obj: child });
          arrayKey = null;
        }
      } else if (val === '|') {
        // Multiline string
        multilineKey = key;
        multilineIndent = indent;
        multilineLines = [];
        multilineTarget = parent;
      } else {
        parent[key] = coerceValue(val);
        // If this is at a different scope than arrayKey, clear array tracking
        if (indent <= arrayItemIndent - 2) {
          arrayKey = null;
        }
      }
    }
  }

  // Flush any remaining multiline or array state
  if (multilineKey !== null) {
    multilineTarget[multilineKey] = multilineLines.join('\n').replace(/\n+$/, '');
  }
  if (currentArrayItem && arrayKey) {
    pushToArray(arrayTarget, arrayKey, currentArrayItem);
  }

  return result;
}

// ─── Config Loading ─────────────────────────────────────────────────────────

/**
 * Load swarm config from filesystem.
 * Returns null if no config file found.
 */
export function loadSwarmYamlConfig(cwd?: string): SwarmYamlConfig | null {
  const workDir = cwd ?? process.cwd();
  const home = homedir();

  const searchPaths = [
    join(workDir, '.attocode', 'swarm.yaml'),
    join(workDir, '.attocode', 'swarm.yml'),
    join(workDir, '.attocode', 'swarm.json'),
    join(home, '.attocode', 'swarm.yaml'),
  ];

  for (const p of searchPaths) {
    if (existsSync(p)) {
      try {
        const content = readFileSync(p, 'utf-8');
        if (p.endsWith('.json')) {
          return JSON.parse(content) as SwarmYamlConfig;
        }
        return parseSwarmYaml(content);
      } catch {
        // Continue to next path
      }
    }
  }

  return null;
}

// ─── Config Mapping ─────────────────────────────────────────────────────────

/**
 * Map parsed YAML config to SwarmConfig fields.
 */
export function yamlToSwarmConfig(
  yaml: SwarmYamlConfig,
  orchestratorModel: string,
): Partial<SwarmConfig> {
  const config: Partial<SwarmConfig> = {};

  // models section
  const models = yaml.models as Record<string, unknown> | undefined;
  if (models) {
    if (models.paidOnly !== undefined) config.paidOnly = Boolean(models.paidOnly);
    if (models.paid_only !== undefined) config.paidOnly = Boolean(models.paid_only);
    if (models.qualityGate || models.quality_gate)
      config.qualityGateModel = String(models.qualityGate ?? models.quality_gate);
    if (models.planner) config.plannerModel = String(models.planner);
    // orchestrator from YAML is a default; CLI --model always overrides
    if (models.orchestrator) config.orchestratorModel = String(models.orchestrator);
  }

  // throttle
  if (yaml.throttle !== undefined) {
    const t = yaml.throttle;
    if (t === 'free' || t === 'paid' || t === false) {
      config.throttle = t as 'free' | 'paid' | false;
    }
  }

  // workers
  const workers = yaml.workers as Array<Record<string, unknown>> | undefined;
  if (workers && Array.isArray(workers)) {
    config.workers = workers.map((w) => {
      const spec: SwarmWorkerSpec = {
        name: String(w.name ?? 'worker'),
        model: String(w.model ?? orchestratorModel),
        capabilities: normalizeCapabilities(
          Array.isArray(w.capabilities)
            ? w.capabilities.map(String)
            : typeof w.capabilities === 'string'
              ? (w.capabilities as string)
                  .replace(/^\[|\]$/g, '')
                  .split(',')
                  .map((s: string) => s.trim())
                  .filter(Boolean)
              : ['code'],
        ),
      };
      if (w.contextWindow) spec.contextWindow = Number(w.contextWindow);
      if (w.persona) spec.persona = String(w.persona);
      if (w.role) spec.role = String(w.role) as SwarmWorkerSpec['role'];
      if (w.maxTokens) spec.maxTokens = Number(w.maxTokens);
      if (w.policyProfile) spec.policyProfile = String(w.policyProfile);
      if (w.allowedTools && Array.isArray(w.allowedTools)) {
        spec.allowedTools = w.allowedTools.map(String);
      }
      if (w.deniedTools && Array.isArray(w.deniedTools)) {
        spec.deniedTools = w.deniedTools.map(String);
      }
      if (w.extraTools) {
        spec.extraTools = Array.isArray(w.extraTools)
          ? w.extraTools.map(String)
          : typeof w.extraTools === 'string'
            ? (w.extraTools as string)
                .replace(/^\[|\]$/g, '')
                .split(',')
                .map((s: string) => s.trim())
                .filter(Boolean)
            : undefined;
      }
      return spec;
    });
  }

  // philosophy
  if (yaml.philosophy) config.philosophy = String(yaml.philosophy);

  // communication
  const comm = yaml.communication as Record<string, unknown> | undefined;
  if (comm) {
    config.communication = {
      blackboard: comm.blackboard !== undefined ? Boolean(comm.blackboard) : undefined,
      dependencyContextMaxLength:
        (comm.dependencyContextMaxLength ?? comm.dependency_context_max_length)
          ? Number(comm.dependencyContextMaxLength ?? comm.dependency_context_max_length)
          : undefined,
      includeFileList:
        (comm.includeFileList ?? comm.include_file_list) !== undefined
          ? Boolean(comm.includeFileList ?? comm.include_file_list)
          : undefined,
    };
  }

  // tasks
  const tasks = yaml.tasks as Record<string, unknown> | undefined;
  if (tasks) {
    if (tasks.maxSubtasks) {
      // Not a direct SwarmConfig field but could be used by decomposer
    }
    if (tasks.priorities && Array.isArray(tasks.priorities)) {
      config.decompositionPriorities = tasks.priorities.map(String);
    }
    if (tasks.fileConflictStrategy) {
      config.fileConflictStrategy = String(
        tasks.fileConflictStrategy,
      ) as SwarmConfig['fileConflictStrategy'];
    }
  }

  // budget
  const budget = yaml.budget as Record<string, unknown> | undefined;
  if (budget) {
    if (budget.totalTokens || budget.total_tokens)
      config.totalBudget = Number(budget.totalTokens ?? budget.total_tokens);
    if (budget.maxCost || budget.max_cost)
      config.maxCost = Number(budget.maxCost ?? budget.max_cost);
    if (budget.maxConcurrency || budget.max_concurrency)
      config.maxConcurrency = Number(budget.maxConcurrency ?? budget.max_concurrency);
    if (budget.maxTokensPerWorker || budget.max_tokens_per_worker)
      config.maxTokensPerWorker = Number(budget.maxTokensPerWorker ?? budget.max_tokens_per_worker);
    if (budget.workerTimeout || budget.worker_timeout)
      config.workerTimeout = Number(budget.workerTimeout ?? budget.worker_timeout);
    if (budget.workerMaxIterations) config.workerMaxIterations = Number(budget.workerMaxIterations);
    if (budget.dispatchStaggerMs || budget.dispatch_stagger_ms)
      config.dispatchStaggerMs = Number(budget.dispatchStaggerMs ?? budget.dispatch_stagger_ms);
    const enforcementMode = budget.enforcementMode ?? budget.enforcement_mode;
    if (enforcementMode !== undefined) {
      const mode = String(enforcementMode);
      if (mode === 'strict' || mode === 'doomloop_only') {
        config.workerEnforcementMode = mode;
      }
    }
  }

  // quality
  const quality = yaml.quality as Record<string, unknown> | undefined;
  if (quality) {
    if (quality.enabled !== undefined) config.qualityGates = Boolean(quality.enabled);
    if (quality.gates !== undefined) config.qualityGates = Boolean(quality.gates);
    if (quality.gateModel || quality.gate_model) {
      config.qualityGateModel = String(quality.gateModel ?? quality.gate_model);
    }
    // minScore, skipOnRetry, skipUnderPressure not in SwarmConfig yet, but could be added
  }

  // reliability — dispatch cap + hollow termination
  const reliability = yaml.reliability as Record<string, unknown> | undefined;
  if (reliability) {
    if (
      reliability.maxDispatchesPerTask !== undefined ||
      reliability.max_dispatches_per_task !== undefined
    ) {
      config.maxDispatchesPerTask = Number(
        reliability.maxDispatchesPerTask ?? reliability.max_dispatches_per_task,
      );
    }
    if (
      reliability.hollowTerminationRatio !== undefined ||
      reliability.hollow_termination_ratio !== undefined
    ) {
      config.hollowTerminationRatio = Number(
        reliability.hollowTerminationRatio ?? reliability.hollow_termination_ratio,
      );
    }
    if (
      reliability.hollowTerminationMinDispatches !== undefined ||
      reliability.hollow_termination_min_dispatches !== undefined
    ) {
      config.hollowTerminationMinDispatches = Number(
        reliability.hollowTerminationMinDispatches ?? reliability.hollow_termination_min_dispatches,
      );
    }
    if (
      reliability.enableHollowTermination !== undefined ||
      reliability.enable_hollow_termination !== undefined
    ) {
      config.enableHollowTermination = Boolean(
        reliability.enableHollowTermination ?? reliability.enable_hollow_termination,
      );
    }
  }

  // taskTypes — per-task-type configuration
  const taskTypes = yaml.taskTypes as Record<string, Record<string, unknown>> | undefined;
  if (taskTypes && typeof taskTypes === 'object') {
    config.taskTypes = {};
    for (const [typeName, typeConfig] of Object.entries(taskTypes)) {
      if (!typeConfig || typeof typeConfig !== 'object') continue;
      const parsed: Record<string, unknown> = {};
      if (typeConfig.timeout !== undefined) parsed.timeout = Number(typeConfig.timeout);
      if (typeConfig.maxIterations !== undefined)
        parsed.maxIterations = Number(typeConfig.maxIterations);
      if (typeConfig.idleTimeout !== undefined) parsed.idleTimeout = Number(typeConfig.idleTimeout);
      if (typeConfig.policyProfile !== undefined)
        parsed.policyProfile = String(typeConfig.policyProfile);
      if (typeConfig.capability !== undefined) parsed.capability = String(typeConfig.capability);
      if (typeConfig.requiresToolCalls !== undefined)
        parsed.requiresToolCalls = Boolean(typeConfig.requiresToolCalls);
      if (typeConfig.promptTemplate !== undefined)
        parsed.promptTemplate = String(typeConfig.promptTemplate);
      if (typeConfig.tools && Array.isArray(typeConfig.tools))
        parsed.tools = typeConfig.tools.map(String);
      if (typeConfig.retries !== undefined) parsed.retries = Number(typeConfig.retries);
      if (typeConfig.tokenBudget !== undefined) parsed.tokenBudget = Number(typeConfig.tokenBudget);
      config.taskTypes[typeName] = parsed as import('./types.js').TaskTypeConfig;
    }
  }

  // resilience
  const resilience = yaml.resilience as Record<string, unknown> | undefined;
  if (resilience) {
    if (resilience.maxConcurrency !== undefined || resilience.max_concurrency !== undefined) {
      config.maxConcurrency = Number(resilience.maxConcurrency ?? resilience.max_concurrency);
    }
    if (
      resilience.dispatchStaggerMs !== undefined ||
      resilience.dispatch_stagger_ms !== undefined
    ) {
      config.dispatchStaggerMs = Number(
        resilience.dispatchStaggerMs ?? resilience.dispatch_stagger_ms,
      );
    }
    if (resilience.workerRetries !== undefined || resilience.worker_retries !== undefined) {
      config.workerRetries = Number(resilience.workerRetries ?? resilience.worker_retries);
    }
    if (
      resilience.dispatchLeaseStaleMs !== undefined ||
      resilience.dispatch_lease_stale_ms !== undefined
    ) {
      config.dispatchLeaseStaleMs = Number(
        resilience.dispatchLeaseStaleMs ?? resilience.dispatch_lease_stale_ms,
      );
    }
    if (resilience.rateLimitRetries !== undefined || resilience.rate_limit_retries !== undefined) {
      config.rateLimitRetries = Number(
        resilience.rateLimitRetries ?? resilience.rate_limit_retries,
      );
    }
    if (resilience.modelFailover !== undefined)
      config.enableModelFailover = Boolean(resilience.modelFailover);
    if (resilience.model_failover !== undefined)
      config.enableModelFailover = Boolean(resilience.model_failover);
  }

  // hierarchy
  const hierarchy = yaml.hierarchy as Record<string, unknown> | undefined;
  if (hierarchy) {
    config.hierarchy = {};
    const manager = hierarchy.manager as Record<string, unknown> | undefined;
    if (manager) {
      config.hierarchy.manager = {
        model: manager.model ? String(manager.model) : undefined,
        persona: manager.persona ? String(manager.persona) : undefined,
      };
    }
    const judge = hierarchy.judge as Record<string, unknown> | undefined;
    if (judge) {
      config.hierarchy.judge = {
        model: judge.model ? String(judge.model) : undefined,
        persona: judge.persona ? String(judge.persona) : undefined,
      };
    }
  }

  // features
  const features = yaml.features as Record<string, unknown> | undefined;
  if (features) {
    if (features.planning !== undefined) config.enablePlanning = Boolean(features.planning);
    if (features.waveReview !== undefined) config.enableWaveReview = Boolean(features.waveReview);
    if (features.wave_review !== undefined) config.enableWaveReview = Boolean(features.wave_review);
    if (features.verification !== undefined)
      config.enableVerification = Boolean(features.verification);
    if (features.persistence !== undefined)
      config.enablePersistence = Boolean(features.persistence);
  }

  // permissions — sandbox and approval overrides for swarm workers
  const permissions = yaml.permissions as Record<string, unknown> | undefined;
  if (permissions) {
    config.permissions = {};
    if (permissions.mode)
      config.permissions.mode = String(permissions.mode) as
        | 'auto-safe'
        | 'interactive'
        | 'strict'
        | 'yolo';
    if (permissions.auto_approve && Array.isArray(permissions.auto_approve)) {
      config.permissions.autoApprove = permissions.auto_approve.map(String);
    }
    if (permissions.autoApprove && Array.isArray(permissions.autoApprove)) {
      config.permissions.autoApprove = (permissions.autoApprove as unknown[]).map(String);
    }
    if (permissions.scoped_approve) {
      config.permissions.scopedApprove = permissions.scoped_approve as Record<
        string,
        { paths: string[] }
      >;
    }
    if (permissions.scopedApprove) {
      config.permissions.scopedApprove = permissions.scopedApprove as Record<
        string,
        { paths: string[] }
      >;
    }
    if (permissions.require_approval && Array.isArray(permissions.require_approval)) {
      config.permissions.requireApproval = permissions.require_approval.map(String);
    }
    if (permissions.requireApproval && Array.isArray(permissions.requireApproval)) {
      config.permissions.requireApproval = (permissions.requireApproval as unknown[]).map(String);
    }
    if (permissions.allowed_commands && Array.isArray(permissions.allowed_commands)) {
      config.permissions.additionalAllowedCommands = permissions.allowed_commands.map(String);
    }
    if (
      permissions.additionalAllowedCommands &&
      Array.isArray(permissions.additionalAllowedCommands)
    ) {
      config.permissions.additionalAllowedCommands = (
        permissions.additionalAllowedCommands as unknown[]
      ).map(String);
    }
  }

  // policyProfiles — named policy profile definitions
  const policyProfiles = yaml.policyProfiles as Record<string, unknown> | undefined;
  if (policyProfiles && typeof policyProfiles === 'object') {
    config.policyProfiles = policyProfiles as SwarmConfig['policyProfiles'];
  }

  // profileExtensions — additive tool patches for built-in or named profiles
  const profileExtensions = (yaml.profileExtensions ?? yaml.profile_extensions) as
    | Record<string, Record<string, unknown>>
    | undefined;
  if (profileExtensions && typeof profileExtensions === 'object') {
    config.profileExtensions = {};
    for (const [profileName, ext] of Object.entries(profileExtensions)) {
      if (!ext || typeof ext !== 'object') continue;
      const entry: { addTools?: string[]; removeTools?: string[] } = {};
      if (ext.addTools && Array.isArray(ext.addTools)) {
        entry.addTools = ext.addTools.map(String);
      }
      if (ext.add_tools && Array.isArray(ext.add_tools)) {
        entry.addTools = (ext.add_tools as unknown[]).map(String);
      }
      if (ext.removeTools && Array.isArray(ext.removeTools)) {
        entry.removeTools = ext.removeTools.map(String);
      }
      if (ext.remove_tools && Array.isArray(ext.remove_tools)) {
        entry.removeTools = (ext.remove_tools as unknown[]).map(String);
      }
      if (entry.addTools || entry.removeTools) {
        config.profileExtensions[profileName] = entry;
      }
    }
  }

  // autoSplit — pre-dispatch auto-split configuration
  const autoSplit = yaml.autoSplit as Record<string, unknown> | undefined;
  if (autoSplit) {
    config.autoSplit = {};
    if (autoSplit.enabled !== undefined) config.autoSplit.enabled = Boolean(autoSplit.enabled);
    if (autoSplit.complexityFloor !== undefined)
      config.autoSplit.complexityFloor = Number(autoSplit.complexityFloor);
    if (autoSplit.maxSubtasks !== undefined)
      config.autoSplit.maxSubtasks = Number(autoSplit.maxSubtasks);
    if (autoSplit.splittableTypes && Array.isArray(autoSplit.splittableTypes)) {
      config.autoSplit.splittableTypes = autoSplit.splittableTypes.map(String);
    }
  }

  // facts — user-configurable grounding facts
  const facts = yaml.facts as Record<string, unknown> | undefined;
  if (facts) {
    config.facts = {};
    if (facts.currentDate) config.facts.currentDate = String(facts.currentDate);
    if (facts.currentYear) config.facts.currentYear = Number(facts.currentYear);
    if (facts.custom && Array.isArray(facts.custom)) {
      config.facts.custom = facts.custom.map(String);
    } else if (typeof facts.custom === 'string') {
      config.facts.custom = [String(facts.custom)];
    }
  }

  return config;
}

// ─── Config Merge ───────────────────────────────────────────────────────────

/**
 * Merge configs: DEFAULT < yaml < CLI overrides.
 */
export function mergeSwarmConfigs(
  defaults: typeof DEFAULT_SWARM_CONFIG,
  yamlConfig: Partial<SwarmConfig> | null,
  cliOverrides: {
    paidOnly?: boolean;
    orchestratorModel: string;
    orchestratorModelExplicit?: boolean;
    resumeSessionId?: string;
  },
): SwarmConfig {
  // Start with defaults + orchestratorModel
  const merged: SwarmConfig = {
    ...defaults,
    orchestratorModel: cliOverrides.orchestratorModel,
    workers: [],
  };

  // Apply YAML config
  if (yamlConfig) {
    for (const [key, value] of Object.entries(yamlConfig)) {
      if (value !== undefined && value !== null) {
        (merged as unknown as Record<string, unknown>)[key] = value;
      }
    }
  }

  // Apply CLI overrides (highest priority)
  // V7: Only re-apply orchestratorModel if the user explicitly passed --model.
  // Otherwise, let the YAML orchestrator setting (applied above) take precedence.
  if (cliOverrides.orchestratorModelExplicit) {
    merged.orchestratorModel = cliOverrides.orchestratorModel;
  }
  if (cliOverrides.paidOnly !== undefined) {
    merged.paidOnly = cliOverrides.paidOnly;
  }
  if (cliOverrides.resumeSessionId) {
    merged.resumeSessionId = cliOverrides.resumeSessionId;
  }

  // When paidOnly and no explicit throttle from yaml: default to 'paid'
  if (merged.paidOnly && !yamlConfig?.throttle) {
    merged.throttle = 'paid';
  }

  return merged;
}

// ─── Model ID Normalization ──────────────────────────────────────────────────

const KNOWN_MODEL_PROVIDERS = new Set([
  'openai',
  'anthropic',
  'google',
  'meta-llama',
  'mistralai',
  'deepseek',
  'qwen',
  'z-ai',
  'moonshotai',
  'x-ai',
  'cohere',
  'openrouter',
  'perplexity',
  'microsoft',
  'nvidia',
  'amazon',
  'alibaba',
  'allenai',
]);

function normalizeSingleModelId(
  raw: string | undefined,
  fallback: string,
): { model: string; changed: boolean; valid: boolean } {
  const value = (raw ?? '').trim();
  if (!value) {
    return { model: fallback, changed: true, valid: false };
  }

  const parts = value
    .split('/')
    .map((p) => p.trim())
    .filter(Boolean);
  if (parts.length === 2) {
    return { model: value, changed: false, valid: true };
  }

  // Common malformed shape: "anthropic/z-ai/glm-5" -> "z-ai/glm-5"
  if (
    parts.length >= 3 &&
    KNOWN_MODEL_PROVIDERS.has(parts[0]) &&
    KNOWN_MODEL_PROVIDERS.has(parts[1])
  ) {
    const normalized = `${parts[1]}/${parts.slice(2).join('/')}`;
    return { model: normalized, changed: normalized !== value, valid: true };
  }

  return { model: fallback, changed: fallback !== value, valid: false };
}

/**
 * Normalize and validate model IDs in swarm config.
 * Auto-corrects common malformed IDs and falls back to orchestrator model on invalid values.
 */
export function normalizeSwarmModelConfig(config: SwarmConfig): {
  config: SwarmConfig;
  warnings: string[];
} {
  const warnings: string[] = [];
  const normalized: SwarmConfig = { ...config };
  normalized.workers = config.workers.map((w) => ({ ...w }));
  if (config.hierarchy) {
    normalized.hierarchy = {
      manager: config.hierarchy.manager ? { ...config.hierarchy.manager } : undefined,
      judge: config.hierarchy.judge ? { ...config.hierarchy.judge } : undefined,
    };
  }

  // Normalize workers first so orchestrator can use a known-good fallback if needed.
  for (let i = 0; i < normalized.workers.length; i++) {
    const worker = normalized.workers[i];
    const result = normalizeSingleModelId(worker.model, config.orchestratorModel);
    if (result.changed || !result.valid) {
      warnings.push(
        `[workers.${i}.model] "${worker.model}" -> "${result.model}"${result.valid ? ' (autocorrected)' : ' (fallback applied)'}`,
      );
      worker.model = result.model;
    }
  }

  const fallbackModel = normalized.workers[0]?.model || config.orchestratorModel;
  const orchestrator = normalizeSingleModelId(config.orchestratorModel, fallbackModel);
  if (orchestrator.changed || !orchestrator.valid) {
    warnings.push(
      `[orchestratorModel] "${config.orchestratorModel}" -> "${orchestrator.model}"${orchestrator.valid ? ' (autocorrected)' : ' (fallback applied)'}`,
    );
    normalized.orchestratorModel = orchestrator.model;
  }

  const planner = normalizeSingleModelId(config.plannerModel, normalized.orchestratorModel);
  if (config.plannerModel && (planner.changed || !planner.valid)) {
    warnings.push(
      `[plannerModel] "${config.plannerModel}" -> "${planner.model}"${planner.valid ? ' (autocorrected)' : ' (fallback applied)'}`,
    );
    normalized.plannerModel = planner.model;
  }

  const quality = normalizeSingleModelId(config.qualityGateModel, normalized.orchestratorModel);
  if (config.qualityGateModel && (quality.changed || !quality.valid)) {
    warnings.push(
      `[qualityGateModel] "${config.qualityGateModel}" -> "${quality.model}"${quality.valid ? ' (autocorrected)' : ' (fallback applied)'}`,
    );
    normalized.qualityGateModel = quality.model;
  }

  if (normalized.hierarchy?.manager?.model) {
    const manager = normalizeSingleModelId(
      normalized.hierarchy.manager.model,
      normalized.orchestratorModel,
    );
    if (manager.changed || !manager.valid) {
      warnings.push(
        `[hierarchy.manager.model] "${normalized.hierarchy.manager.model}" -> "${manager.model}"${manager.valid ? ' (autocorrected)' : ' (fallback applied)'}`,
      );
      normalized.hierarchy.manager.model = manager.model;
    }
  }

  if (normalized.hierarchy?.judge?.model) {
    const judge = normalizeSingleModelId(
      normalized.hierarchy.judge.model,
      normalized.orchestratorModel,
    );
    if (judge.changed || !judge.valid) {
      warnings.push(
        `[hierarchy.judge.model] "${normalized.hierarchy.judge.model}" -> "${judge.model}"${judge.valid ? ' (autocorrected)' : ' (fallback applied)'}`,
      );
      normalized.hierarchy.judge.model = judge.model;
    }
  }

  return { config: normalized, warnings };
}

// ─── Capability Normalization ────────────────────────────────────────────────

const VALID_CAPABILITIES = new Set<WorkerCapability>([
  'code',
  'research',
  'review',
  'test',
  'document',
  'write',
]);

const CAPABILITY_ALIASES: Record<string, WorkerCapability> = {
  refactor: 'code',
  implement: 'code',
  coding: 'code',
  writing: 'write',
  synthesis: 'write',
  synthesize: 'write',
  merge: 'write',
  docs: 'document',
  documentation: 'document',
  testing: 'test',
  reviewing: 'review',
  researching: 'research',
};

/**
 * Normalize capability strings from YAML config.
 * - Passes valid capabilities through
 * - Maps known aliases (refactor→code, writing→write, etc.)
 * - Drops unknown values silently
 * - Falls back to ['code'] if empty after filtering
 */
export function normalizeCapabilities(raw: string[]): WorkerCapability[] {
  const result: WorkerCapability[] = [];
  const seen = new Set<WorkerCapability>();

  for (const cap of raw) {
    const lower = cap.toLowerCase().trim();
    let resolved: WorkerCapability | undefined;

    if (VALID_CAPABILITIES.has(lower as WorkerCapability)) {
      resolved = lower as WorkerCapability;
    } else if (CAPABILITY_ALIASES[lower]) {
      resolved = CAPABILITY_ALIASES[lower];
    }

    if (resolved && !seen.has(resolved)) {
      seen.add(resolved);
      result.push(resolved);
    }
  }

  return result.length > 0 ? result : ['code'];
}

// ─── Helper Functions ───────────────────────────────────────────────────────

function getIndent(line: string): number {
  const match = line.match(/^(\s*)/);
  return match ? match[1].length : 0;
}

function splitKeyValue(s: string): [string, string] {
  const idx = s.indexOf(':');
  if (idx === -1) return ['', s];
  const key = s.slice(0, idx).trim();
  const val = s.slice(idx + 1).trim();
  // Remove surrounding quotes
  if ((val.startsWith("'") && val.endsWith("'")) || (val.startsWith('"') && val.endsWith('"'))) {
    return [key, val.slice(1, -1)];
  }
  return [key, val];
}

function coerceValue(val: string): unknown {
  if (val === 'true') return true;
  if (val === 'false') return false;
  if (val === 'null' || val === '~') return null;
  if (val === '') return '';
  // Check for number
  if (/^-?\d+(\.\d+)?$/.test(val)) {
    const num = Number(val);
    if (!isNaN(num)) return num;
  }
  // Remove surrounding quotes
  if ((val.startsWith("'") && val.endsWith("'")) || (val.startsWith('"') && val.endsWith('"'))) {
    return val.slice(1, -1);
  }
  return val;
}

function stripInlineComment(s: string): string {
  // Don't strip # inside quoted strings
  let inSingle = false;
  let inDouble = false;
  for (let i = 0; i < s.length; i++) {
    if (s[i] === "'" && !inDouble) inSingle = !inSingle;
    if (s[i] === '"' && !inSingle) inDouble = !inDouble;
    if (s[i] === '#' && !inSingle && !inDouble && i > 0 && s[i - 1] === ' ') {
      return s.slice(0, i).trim();
    }
  }
  return s;
}

function pushToArray(obj: Record<string, unknown>, key: string, value: unknown): void {
  if (!Array.isArray(obj[key])) {
    obj[key] = [];
  }
  (obj[key] as unknown[]).push(value);
}

function peekNextContent(lines: string[], from: number): { raw: string; trimmed: string } | null {
  for (let i = from; i < lines.length; i++) {
    const trimmed = lines[i].trim();
    if (trimmed !== '' && !trimmed.startsWith('#')) {
      return { raw: lines[i], trimmed };
    }
  }
  return null;
}
