/**
 * Zod schemas for user-facing configuration (config.json).
 *
 * Validates the serializable subset of config that users write in
 * `~/.config/attocode/config.json` or `.attocode/config.json`.
 */

import { z } from 'zod';

// =============================================================================
// FEATURE SUB-SCHEMAS
// =============================================================================

/**
 * Helper: a feature section that can be an object or `false` to disable.
 */
function featureSection<T extends z.ZodRawShape>(shape: T) {
  return z.union([z.object(shape).strict(), z.literal(false)]);
}

const PlanningSchema = z
  .object({
    enabled: z.boolean().optional(),
    autoplan: z.boolean().optional(),
    complexityThreshold: z.number().int().positive().optional(),
    maxDepth: z.number().int().positive().optional(),
    allowReplan: z.boolean().optional(),
  })
  .strict();

const MemorySchema = z
  .object({
    enabled: z.boolean().optional(),
    types: z
      .object({
        episodic: z.boolean().optional(),
        semantic: z.boolean().optional(),
        working: z.boolean().optional(),
      })
      .optional(),
    retrievalStrategy: z.enum(['recency', 'relevance', 'importance', 'hybrid']).optional(),
    retrievalLimit: z.number().int().positive().optional(),
    persistPath: z.string().optional(),
    maxEpisodicEntries: z.number().int().positive().optional(),
    maxSemanticEntries: z.number().int().positive().optional(),
  })
  .strict();

const SandboxSchema = z
  .object({
    enabled: z.boolean().optional(),
    isolation: z.enum(['none', 'process', 'container']).optional(),
    mode: z.enum(['auto', 'seatbelt', 'docker', 'basic', 'none']).optional(),
    allowedCommands: z.array(z.string()).optional(),
    blockedCommands: z.array(z.string()).optional(),
    networkAllowed: z.boolean().optional(),
    dockerImage: z.string().optional(),
  })
  .strict();

const PolicyEngineSchema = z
  .object({
    enabled: z.boolean().optional(),
    legacyFallback: z.boolean().optional(),
    defaultProfile: z.string().optional(),
    defaultSwarmProfile: z.string().optional(),
    profiles: z.record(z.string(), z.any()).optional(),
  })
  .strict();

const HumanInLoopSchema = z
  .object({
    enabled: z.boolean().optional(),
    riskThreshold: z.enum(['low', 'moderate', 'high', 'critical']).optional(),
    alwaysApprove: z.array(z.string()).optional(),
    neverApprove: z.array(z.string()).optional(),
    approvalTimeout: z.number().int().positive().optional(),
    auditLog: z.boolean().optional(),
  })
  .strict();

const SubagentSchema = z
  .object({
    enabled: z.boolean().optional(),
    defaultTimeout: z.number().int().positive().optional(),
    defaultMaxIterations: z.number().int().positive().optional(),
    inheritObservability: z.boolean().optional(),
    wrapupWindowMs: z.number().int().nonnegative().optional(),
    idleCheckIntervalMs: z.number().int().positive().optional(),
  })
  .strict();

const ObservabilitySchema = z
  .object({
    enabled: z.boolean().optional(),
    tracing: z
      .object({
        enabled: z.boolean().optional(),
        serviceName: z.string().optional(),
        exporter: z.enum(['console', 'otlp', 'custom']).optional(),
      })
      .optional(),
    metrics: z
      .object({
        enabled: z.boolean().optional(),
        collectTokens: z.boolean().optional(),
        collectCosts: z.boolean().optional(),
        collectLatencies: z.boolean().optional(),
      })
      .optional(),
    logging: z
      .object({
        enabled: z.boolean().optional(),
        level: z.enum(['debug', 'info', 'warn', 'error']).optional(),
        structured: z.boolean().optional(),
      })
      .optional(),
  })
  .strict();

const CancellationSchema = z
  .object({
    enabled: z.boolean().optional(),
    defaultTimeout: z.number().int().nonnegative().optional(),
    gracePeriod: z.number().int().nonnegative().optional(),
  })
  .strict();

const ResourcesSchema = z
  .object({
    enabled: z.boolean().optional(),
    maxMemoryMB: z.number().positive().optional(),
    maxCpuTimeSec: z.number().positive().optional(),
    maxConcurrentOps: z.number().int().positive().optional(),
    warnThreshold: z.number().min(0).max(1).optional(),
    criticalThreshold: z.number().min(0).max(1).optional(),
  })
  .strict();

const CompactionSchema = z
  .object({
    enabled: z.boolean().optional(),
    tokenThreshold: z.number().int().positive().optional(),
    preserveRecentCount: z.number().int().nonnegative().optional(),
    preserveToolResults: z.boolean().optional(),
    summaryMaxTokens: z.number().int().positive().optional(),
    summaryModel: z.string().optional(),
    mode: z.enum(['auto', 'approval', 'manual']).optional(),
  })
  .strict();

// =============================================================================
// PROVIDER RESILIENCE
// =============================================================================

const CircuitBreakerSchema = z.union([
  z
    .object({
      failureThreshold: z.number().int().positive().optional(),
      resetTimeout: z.number().int().positive().optional(),
      halfOpenRequests: z.number().int().positive().optional(),
      tripOnErrors: z
        .array(z.enum(['RATE_LIMITED', 'SERVER_ERROR', 'NETWORK_ERROR', 'TIMEOUT', 'ALL']))
        .optional(),
    })
    .strict(),
  z.literal(false),
]);

const ProviderResilienceSchema = z
  .object({
    enabled: z.boolean().optional(),
    circuitBreaker: CircuitBreakerSchema.optional(),
    fallbackProviders: z.array(z.string()).optional(),
    fallbackChain: z
      .object({
        cooldownMs: z.number().int().positive().optional(),
        failureThreshold: z.number().int().positive().optional(),
      })
      .strict()
      .optional(),
  })
  .strict();

// =============================================================================
// TOP-LEVEL USER CONFIG SCHEMA
// =============================================================================

/**
 * Zod schema for user-facing config.json files.
 *
 * Uses `.passthrough()` at the top level to avoid breaking users with custom fields.
 * Feature sub-schemas use `.strict()` to catch typos in feature-specific keys.
 */
export const UserConfigSchema = z
  .object({
    // Core scalars
    model: z.string().optional(),
    maxIterations: z.number().int().positive().optional(),
    timeout: z.number().int().positive().optional(),
    maxTokens: z.number().int().positive().optional(),
    temperature: z.number().min(0).max(2).optional(),

    // Provider selection
    providers: z
      .object({
        default: z.string().optional(),
      })
      .strict()
      .optional(),

    // Provider resilience
    providerResilience: ProviderResilienceSchema.optional(),

    // Feature sections (object | false)
    planning: featureSection(PlanningSchema.shape).optional(),
    memory: featureSection(MemorySchema.shape).optional(),
    sandbox: featureSection(SandboxSchema.shape).optional(),
    policyEngine: featureSection(PolicyEngineSchema.shape).optional(),
    humanInLoop: featureSection(HumanInLoopSchema.shape).optional(),
    subagent: featureSection(SubagentSchema.shape).optional(),
    observability: featureSection(ObservabilitySchema.shape).optional(),
    cancellation: featureSection(CancellationSchema.shape).optional(),
    resources: featureSection(ResourcesSchema.shape).optional(),
    compaction: featureSection(CompactionSchema.shape).optional(),
  })
  .passthrough();

/**
 * Validated user config type inferred from the schema.
 */
export type ValidatedUserConfig = z.infer<typeof UserConfigSchema>;
