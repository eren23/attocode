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
        if (indent <= (arrayItemIndent - 2)) {
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
export function yamlToSwarmConfig(yaml: SwarmYamlConfig, orchestratorModel: string): Partial<SwarmConfig> {
  const config: Partial<SwarmConfig> = {};

  // models section
  const models = yaml.models as Record<string, unknown> | undefined;
  if (models) {
    if (models.paidOnly !== undefined) config.paidOnly = Boolean(models.paidOnly);
    if (models.paid_only !== undefined) config.paidOnly = Boolean(models.paid_only);
    if (models.qualityGate) config.qualityGateModel = String(models.qualityGate);
    if (models.planner) config.plannerModel = String(models.planner);
    // models.orchestrator: null means use --model flag (handled by merge)
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
    config.workers = workers.map(w => {
      const spec: SwarmWorkerSpec = {
        name: String(w.name ?? 'worker'),
        model: String(w.model ?? orchestratorModel),
        capabilities: (Array.isArray(w.capabilities)
          ? w.capabilities.map(String)
          : typeof w.capabilities === 'string'
            ? (w.capabilities as string).replace(/^\[|\]$/g, '').split(',').map((s: string) => s.trim()).filter(Boolean)
            : ['code']) as WorkerCapability[],
      };
      if (w.contextWindow) spec.contextWindow = Number(w.contextWindow);
      if (w.persona) spec.persona = String(w.persona);
      if (w.role) spec.role = String(w.role) as SwarmWorkerSpec['role'];
      if (w.maxTokens) spec.maxTokens = Number(w.maxTokens);
      if (w.allowedTools && Array.isArray(w.allowedTools)) {
        spec.allowedTools = w.allowedTools.map(String);
      }
      if (w.deniedTools && Array.isArray(w.deniedTools)) {
        spec.deniedTools = w.deniedTools.map(String);
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
      dependencyContextMaxLength: comm.dependencyContextMaxLength
        ? Number(comm.dependencyContextMaxLength) : undefined,
      includeFileList: comm.includeFileList !== undefined ? Boolean(comm.includeFileList) : undefined,
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
      config.fileConflictStrategy = String(tasks.fileConflictStrategy) as SwarmConfig['fileConflictStrategy'];
    }
  }

  // budget
  const budget = yaml.budget as Record<string, unknown> | undefined;
  if (budget) {
    if (budget.totalTokens || budget.total_tokens) config.totalBudget = Number(budget.totalTokens ?? budget.total_tokens);
    if (budget.maxCost || budget.max_cost) config.maxCost = Number(budget.maxCost ?? budget.max_cost);
    if (budget.maxConcurrency || budget.max_concurrency) config.maxConcurrency = Number(budget.maxConcurrency ?? budget.max_concurrency);
    if (budget.maxTokensPerWorker || budget.max_tokens_per_worker) config.maxTokensPerWorker = Number(budget.maxTokensPerWorker ?? budget.max_tokens_per_worker);
    if (budget.workerTimeout || budget.worker_timeout) config.workerTimeout = Number(budget.workerTimeout ?? budget.worker_timeout);
    if (budget.workerMaxIterations) config.workerMaxIterations = Number(budget.workerMaxIterations);
    if (budget.dispatchStaggerMs) config.dispatchStaggerMs = Number(budget.dispatchStaggerMs);
  }

  // quality
  const quality = yaml.quality as Record<string, unknown> | undefined;
  if (quality) {
    if (quality.enabled !== undefined) config.qualityGates = Boolean(quality.enabled);
    // minScore, skipOnRetry, skipUnderPressure not in SwarmConfig yet, but could be added
  }

  // resilience
  const resilience = yaml.resilience as Record<string, unknown> | undefined;
  if (resilience) {
    if (resilience.workerRetries !== undefined) config.workerRetries = Number(resilience.workerRetries);
    if (resilience.rateLimitRetries !== undefined) config.rateLimitRetries = Number(resilience.rateLimitRetries);
    if (resilience.modelFailover !== undefined) config.enableModelFailover = Boolean(resilience.modelFailover);
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
    if (features.verification !== undefined) config.enableVerification = Boolean(features.verification);
    if (features.persistence !== undefined) config.enablePersistence = Boolean(features.persistence);
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
  cliOverrides: { paidOnly?: boolean; orchestratorModel: string; resumeSessionId?: string },
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
