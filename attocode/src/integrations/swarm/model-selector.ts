/**
 * Swarm Model Selector
 *
 * Auto-detects the cheapest function-calling models via OpenRouter's API.
 * Falls back to hardcoded defaults when the API is unavailable.
 */

import type { SwarmWorkerSpec, WorkerCapability, ModelHealthRecord } from './types.js';

// ─── OpenRouter Model API Types ────────────────────────────────────────────

interface OpenRouterModel {
  id: string;
  name: string;
  pricing: {
    prompt: string;  // cost per token as string
    completion: string;
  };
  context_length: number;
  architecture?: {
    modality?: string;
    tokenizer?: string;
    instruct_type?: string;
  };
  supported_parameters?: string[];
  // Some models have this field for tool/function calling
  description?: string;
}

interface OpenRouterModelsResponse {
  data: OpenRouterModel[];
}

// ─── Hardcoded Fallbacks ───────────────────────────────────────────────────

export const FALLBACK_WORKERS: SwarmWorkerSpec[] = [
  // ── Coders (3 models, provider-diverse paid models for independent rate limit pools) ──
  {
    name: 'coder',
    model: 'mistralai/mistral-large-2512',
    capabilities: ['code', 'test'],
    contextWindow: 262144,
    allowedTools: ['read_file', 'write_file', 'edit_file', 'glob', 'grep', 'bash'],
    policyProfile: 'code-strict-bash',
  },
  {
    name: 'coder-alt',
    model: 'z-ai/glm-4.7-flash',
    capabilities: ['code', 'test'],
    contextWindow: 202000,
    allowedTools: ['read_file', 'write_file', 'edit_file', 'glob', 'grep', 'bash'],
    policyProfile: 'code-strict-bash',
  },
  {
    name: 'coder-alt2',
    model: 'allenai/olmo-3.1-32b-instruct',
    capabilities: ['code', 'test'],
    contextWindow: 65536,
    allowedTools: ['read_file', 'write_file', 'edit_file', 'glob', 'grep', 'bash'],
    policyProfile: 'code-strict-bash',
  },
  // ── Researcher (separate provider from all coders) ──
  {
    name: 'researcher',
    model: 'moonshotai/kimi-k2.5-0127',
    capabilities: ['research', 'review'],
    contextWindow: 262144,
    allowedTools: ['read_file', 'list_files', 'glob', 'grep'],
    policyProfile: 'research-safe',
  },
  // ── Documenter (cheap, shares Mistral pool but low usage) ──
  {
    name: 'documenter',
    model: 'mistralai/ministral-14b-2512',
    capabilities: ['document'],
    contextWindow: 262144,
    allowedTools: ['read_file', 'write_file', 'glob'],
    policyProfile: 'code-strict-bash',
  },
];

// ─── Model Selection ───────────────────────────────────────────────────────

/**
 * Options for model auto-detection.
 */
export interface ModelSelectorOptions {
  /** OpenRouter API key */
  apiKey: string;

  /** Orchestrator model (used as reviewer fallback) */
  orchestratorModel: string;

  /** Minimum context window size (default: 8192) */
  minContextWindow?: number;

  /** Maximum cost per million tokens (prompt + completion, default: 5.0) */
  maxCostPerMillion?: number;

  /** Preferred models to try first (exact model IDs) */
  preferredModels?: string[];

  /** Only use paid models (filter out free tier) */
  paidOnly?: boolean;
}

/**
 * Auto-detect the cheapest worker models from OpenRouter.
 *
 * Queries `/api/v1/models`, filters by tool use support and cost,
 * then assigns models to capability roles.
 */
export async function autoDetectWorkerModels(options: ModelSelectorOptions): Promise<SwarmWorkerSpec[]> {
  try {
    const models = await fetchOpenRouterModels(options.apiKey);
    if (!models || models.length === 0) {
      return getFallbackWorkers(options.orchestratorModel);
    }

    // Filter for usable models
    const minContext = options.minContextWindow ?? 32768;
    const maxCost = options.maxCostPerMillion ?? 5.0;

    const usable = models.filter(m => {
      const contextLen = m.context_length ?? 0;
      if (contextLen < minContext) return false;

      const promptCost = parseFloat(m.pricing?.prompt ?? '999');
      const completionCost = parseFloat(m.pricing?.completion ?? '999');
      // M3: Guard against NaN from non-numeric strings like 'free'
      if (isNaN(promptCost) || isNaN(completionCost)) return false;
      // Cost per million tokens
      const costPerMillion = (promptCost + completionCost) * 1_000_000;
      if (costPerMillion > maxCost) return false;

      // paidOnly: filter out free-tier models
      if (options.paidOnly) {
        const promptCostVal = parseFloat(m.pricing?.prompt ?? '0');
        const completionCostVal = parseFloat(m.pricing?.completion ?? '0');
        if (promptCostVal === 0 && completionCostVal === 0) return false;
        if (m.id.endsWith(':free')) return false;
      }

      // Use the authoritative `supported_parameters` field from the API
      // Models that support tool use have 'tools' in this array
      const supportsTools = m.supported_parameters?.includes('tools') ?? false;
      return supportsTools;
    });

    // Sort by cost (cheapest first)
    usable.sort((a, b) => {
      const costA = parseFloat(a.pricing.prompt) + parseFloat(a.pricing.completion);
      const costB = parseFloat(b.pricing.prompt) + parseFloat(b.pricing.completion);
      return costA - costB;
    });

    // Assign to roles — select multiple models per role for round-robin,
    // preferring different providers to maximize rate limit headroom.
    const workers: SwarmWorkerSpec[] = [];
    const usedIds = new Set<string>();
    const usedProvidersGlobal = new Set<string>(); // Track providers across ALL roles

    /** Pick up to N models matching a filter, preferring provider diversity.
     *  Avoids providers already used by other roles to maximize rate limit pools. */
    function pickDiverse(
      pool: OpenRouterModel[],
      filter: (m: OpenRouterModel) => boolean,
      count: number,
    ): OpenRouterModel[] {
      const matching = pool.filter(m => filter(m) && !usedIds.has(m.id));
      const picked: OpenRouterModel[] = [];
      const usedProvidersLocal = new Set<string>();

      // First pass: prefer providers not used by ANY other role
      for (const m of matching) {
        if (picked.length >= count) break;
        const provider = m.id.split('/')[0];
        if (!usedProvidersGlobal.has(provider) && !usedProvidersLocal.has(provider)) {
          usedProvidersLocal.add(provider);
          picked.push(m);
        }
      }
      // Second pass: allow providers used by other roles but not this role
      for (const m of matching) {
        if (picked.length >= count) break;
        const provider = m.id.split('/')[0];
        if (!usedProvidersLocal.has(provider) && !picked.includes(m)) {
          usedProvidersLocal.add(provider);
          picked.push(m);
        }
      }
      // Third pass: fill remaining from any provider
      for (const m of matching) {
        if (picked.length >= count) break;
        if (!picked.includes(m)) picked.push(m);
      }

      for (const m of picked) {
        usedIds.add(m.id);
        usedProvidersGlobal.add(m.id.split('/')[0]);
      }
      return picked;
    }

    // Find coders (up to 3, prefer models with 'coder' in the name first)
    const coderModels = pickDiverse(
      usable,
      m => m.id.toLowerCase().includes('coder') || m.id.toLowerCase().includes('deepseek'),
      3,
    );
    // If we didn't get 3, add more general-purpose models
    if (coderModels.length < 3) {
      const extras = pickDiverse(usable, () => true, 3 - coderModels.length);
      coderModels.push(...extras);
    }

    for (let i = 0; i < coderModels.length; i++) {
      const m = coderModels[i];
      workers.push({
        name: i === 0 ? 'coder' : `coder-alt${i}`,
        model: m.id,
        capabilities: ['code', 'test'],
        contextWindow: m.context_length,
        allowedTools: ['read_file', 'write_file', 'edit_file', 'glob', 'grep', 'bash'],
        policyProfile: 'code-strict-bash',
      });
    }

    // Find researchers (up to 2, prefer large context)
    const researchPool = usable.filter(m => !usedIds.has(m.id))
      .sort((a, b) => (b.context_length ?? 0) - (a.context_length ?? 0));
    const researcherModels = pickDiverse(researchPool, () => true, 2);
    for (let i = 0; i < researcherModels.length; i++) {
      const m = researcherModels[i];
      workers.push({
        name: i === 0 ? 'researcher' : `researcher-alt${i}`,
        model: m.id,
        capabilities: ['research', 'review'],
        contextWindow: m.context_length,
        allowedTools: ['read_file', 'list_files', 'glob', 'grep'],
        policyProfile: 'research-safe',
      });
    }

    // Documenter — pick one remaining model
    const docModels = pickDiverse(usable, () => true, 1);
    if (docModels.length > 0) {
      workers.push({
        name: 'documenter',
        model: docModels[0].id,
        capabilities: ['document'],
        contextWindow: docModels[0].context_length,
        allowedTools: ['read_file', 'write_file', 'glob'],
        policyProfile: 'code-strict-bash',
      });
    }

    // Reviewer uses orchestrator model (needs quality for judgment)
    workers.push({
      name: 'reviewer',
      model: options.orchestratorModel,
      capabilities: ['review'],
      allowedTools: ['read_file', 'glob', 'grep'],
    });

    // If we got at least 3 workers (coder + researcher + reviewer), use auto-detected
    if (workers.length >= 3) {
      return workers;
    }

    return getFallbackWorkers(options.orchestratorModel);
  } catch {
    return getFallbackWorkers(options.orchestratorModel);
  }
}

/**
 * Fetch models from OpenRouter API.
 */
async function fetchOpenRouterModels(apiKey: string): Promise<OpenRouterModel[]> {
  const response = await fetch('https://openrouter.ai/api/v1/models', {
    headers: {
      'Authorization': `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
    },
  });

  if (!response.ok) {
    return [];
  }

  const data = await response.json() as OpenRouterModelsResponse;
  return data.data ?? [];
}

/**
 * Get fallback worker specs when API detection fails.
 */
function getFallbackWorkers(orchestratorModel: string): SwarmWorkerSpec[] {
  console.warn('[swarm] Using hardcoded fallback workers — no workers configured or API detection failed');
  return [
    ...FALLBACK_WORKERS,
    {
      name: 'reviewer',
      model: orchestratorModel,
      capabilities: ['review'] as WorkerCapability[],
      allowedTools: ['read_file', 'glob', 'grep'],
    },
  ];
}

/**
 * Select the best worker model for a given capability.
 * When multiple workers match, round-robins based on taskIndex
 * to distribute load across different models/providers.
 */
export function selectWorkerForCapability(
  workers: SwarmWorkerSpec[],
  capability: WorkerCapability,
  taskIndex?: number,
  healthTracker?: ModelHealthTracker,
): SwarmWorkerSpec | undefined {
  const matches = workers.filter(w => w.capabilities.includes(capability));

  if (matches.length > 0) {
    if (healthTracker) {
      // F1: Rank by success rate (descending), deprioritize hollow-prone models, then round-robin among top tier
      const ranked = [...matches].sort((a, b) => {
        const healthyA = healthTracker.isHealthy(a.model) ? 1 : 0;
        const healthyB = healthTracker.isHealthy(b.model) ? 1 : 0;
        if (healthyA !== healthyB) return healthyB - healthyA;
        // Deprioritize models with high hollow rates (>15% difference)
        const hollowA = healthTracker.getHollowRate(a.model);
        const hollowB = healthTracker.getHollowRate(b.model);
        if (Math.abs(hollowA - hollowB) > 0.15) return hollowA - hollowB;
        const rateA = healthTracker.getSuccessRate(a.model);
        const rateB = healthTracker.getSuccessRate(b.model);
        return rateB - rateA;
      });
      // Round-robin among top-tier models (same health status and similar success rate)
      const topRate = healthTracker.getSuccessRate(ranked[0].model);
      const topHealthy = healthTracker.isHealthy(ranked[0].model);
      const topTier = ranked.filter(w => {
        const rate = healthTracker.getSuccessRate(w.model);
        return healthTracker.isHealthy(w.model) === topHealthy
          && Math.abs(rate - topRate) < 0.2;
      });
      return topTier[(taskIndex ?? 0) % topTier.length];
    }
    // No health tracker — simple round-robin
    return matches[(taskIndex ?? 0) % matches.length];
  }

  // Fallback: any code-capable worker for code-adjacent tasks
  if (capability === 'test' || capability === 'code') {
    const codeWorkers = workers.filter(w => w.capabilities.includes('code'));
    if (codeWorkers.length > 0) {
      return codeWorkers[(taskIndex ?? 0) % codeWorkers.length];
    }
  }

  // Fallback: write capability falls back to code workers (merge/synthesis tasks)
  if (capability === 'write') {
    const codeWorkers = workers.filter(w => w.capabilities.includes('code'));
    if (codeWorkers.length > 0) {
      return codeWorkers[(taskIndex ?? 0) % codeWorkers.length];
    }
  }

  // Last resort: first worker
  return workers[0];
}

// ─── Model Health Tracker ─────────────────────────────────────────────────

/** Tracks model health for intelligent failover decisions. */
export class ModelHealthTracker {
  private records = new Map<string, ModelHealthRecord>();
  private recentRateLimits = new Map<string, number[]>(); // model → timestamps
  private hollowCounts = new Map<string, number>(); // model → hollow completion count

  private getOrCreate(model: string): ModelHealthRecord {
    let record = this.records.get(model);
    if (!record) {
      record = {
        model,
        successes: 0,
        failures: 0,
        rateLimits: 0,
        averageLatencyMs: 0,
        healthy: true,
        successRate: 1.0,
      };
      this.records.set(model, record);
    }
    return record;
  }

  /** Recompute successRate from current successes/failures. */
  private updateSuccessRate(record: ModelHealthRecord): void {
    const total = record.successes + record.failures;
    record.successRate = total > 0 ? record.successes / total : 1.0;
  }

  recordSuccess(model: string, latencyMs: number): void {
    const record = this.getOrCreate(model);
    record.successes++;
    // Exponential moving average for latency
    record.averageLatencyMs = record.averageLatencyMs === 0
      ? latencyMs
      : record.averageLatencyMs * 0.7 + latencyMs * 0.3;
    record.healthy = true;
    this.updateSuccessRate(record);
  }

  recordFailure(model: string, errorType: '429' | '402' | 'timeout' | 'error'): void {
    const record = this.getOrCreate(model);
    record.failures++;

    if (errorType === '429' || errorType === '402') {
      record.rateLimits++;
      record.lastRateLimit = Date.now();

      // Track recent rate limits for health assessment
      const recent = this.recentRateLimits.get(model) ?? [];
      recent.push(Date.now());
      this.recentRateLimits.set(model, recent);

      // Unhealthy if 2+ rate limits in last 60s
      const cutoff = Date.now() - 60_000;
      const recentCount = recent.filter(t => t > cutoff).length;
      if (recentCount >= 2) {
        record.healthy = false;
      }
    }

    // Unhealthy if >50% failure rate in last 10 attempts
    const total = record.successes + record.failures;
    if (total >= 3 && record.failures / total > 0.5) {
      record.healthy = false;
    }
    this.updateSuccessRate(record);
  }

  /** F19: Directly mark a model as unhealthy (e.g., after probe failure).
   *  Bypasses the statistical threshold — used when we have definitive evidence. */
  markUnhealthy(model: string): void {
    const record = this.getOrCreate(model);
    record.healthy = false;
    this.updateSuccessRate(record);
  }

  recordQualityRejection(model: string, _score: number): void {
    const record = this.getOrCreate(model);
    // Undo premature recordSuccess() that was called before quality gate ran
    if (record.successes > 0) record.successes--;
    record.failures++;
    // Track quality-specific rejections
    record.qualityRejections = (record.qualityRejections ?? 0) + 1;
    // Mark unhealthy at 3 quality rejections or >50% failure rate
    if ((record.qualityRejections ?? 0) >= 3) {
      record.healthy = false;
    }
    const total = record.successes + record.failures;
    if (total >= 3 && record.failures / total > 0.5) {
      record.healthy = false;
    }
    this.updateSuccessRate(record);
  }

  /** Record a hollow completion (worker returned without doing real work).
   *  Also records as a generic failure to preserve existing health logic. */
  recordHollow(model: string): void {
    const count = (this.hollowCounts.get(model) ?? 0) + 1;
    this.hollowCounts.set(model, count);
    // Also record as failure (existing behavior preserved)
    this.recordFailure(model, 'error');
  }

  /** Get the hollow completion rate for a model (0.0-1.0). */
  getHollowRate(model: string): number {
    const record = this.records.get(model);
    if (!record) return 0;
    const total = record.successes + record.failures;
    if (total === 0) return 0;
    return (this.hollowCounts.get(model) ?? 0) / total;
  }

  /** Get the raw hollow completion count for a model. */
  getHollowCount(model: string): number {
    return this.hollowCounts.get(model) ?? 0;
  }

  isHealthy(model: string): boolean {
    const record = this.records.get(model);
    return record?.healthy ?? true; // Unknown models assumed healthy
  }

  getSuccessRate(model: string): number {
    const record = this.records.get(model);
    return record?.successRate ?? 1.0;
  }

  getHealthy(models: string[]): string[] {
    return models.filter(m => this.isHealthy(m));
  }

  getAllRecords(): ModelHealthRecord[] {
    return [...this.records.values()];
  }

  restore(records: ModelHealthRecord[]): void {
    this.records.clear();
    this.recentRateLimits.clear();
    this.hollowCounts.clear();
    for (const record of records) {
      this.records.set(record.model, { ...record });
    }
  }
}

/**
 * Find an alternative model for a failed task.
 * Returns a different worker spec with the same capability, preferring healthy models.
 */
export function selectAlternativeModel(
  workers: SwarmWorkerSpec[],
  failedModel: string,
  capability: WorkerCapability,
  healthTracker: ModelHealthTracker,
): SwarmWorkerSpec | undefined {
  const alternatives = workers.filter(w =>
    w.model !== failedModel &&
    w.capabilities.includes(capability) &&
    healthTracker.isHealthy(w.model),
  );
  if (alternatives.length > 0) return alternatives[0];

  // If no healthy alternatives, try any different model with same capability
  const anyAlternative = workers.filter(w =>
    w.model !== failedModel &&
    w.capabilities.includes(capability),
  );
  if (anyAlternative.length > 0) return anyAlternative[0];

  // Fallback: write capability falls back to code workers (merge/synthesis tasks)
  if (capability === 'write') {
    const codeAlternatives = workers.filter(w =>
      w.model !== failedModel &&
      w.capabilities.includes('code') &&
      healthTracker.isHealthy(w.model),
    );
    if (codeAlternatives.length > 0) return codeAlternatives[0];

    const anyCodeAlt = workers.filter(w =>
      w.model !== failedModel &&
      w.capabilities.includes('code'),
    );
    if (anyCodeAlt.length > 0) return anyCodeAlt[0];
  }

  // No alternative found within configured workers — return undefined.
  // Do NOT fall through to FALLBACK_WORKERS; injecting unconfigured models
  // ("ghost models") causes hollow completions and wasted budget.
  return undefined;
}
