/**
 * Config Schema Validation Tests
 *
 * Tests the Zod schema for user-facing config.json files.
 */

import { describe, it, expect } from 'vitest';
import { UserConfigSchema } from '../../src/config/schema.js';

describe('UserConfigSchema', () => {
  it('accepts empty object', () => {
    const result = UserConfigSchema.safeParse({});
    expect(result.success).toBe(true);
  });

  it('accepts minimal config with just model', () => {
    const result = UserConfigSchema.safeParse({ model: 'claude-sonnet-4-5-20250929' });
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.model).toBe('claude-sonnet-4-5-20250929');
    }
  });

  it('accepts full core scalars', () => {
    const config = {
      model: 'gpt-4',
      maxIterations: 50,
      timeout: 300000,
      maxTokens: 4096,
      temperature: 0.7,
    };
    const result = UserConfigSchema.safeParse(config);
    expect(result.success).toBe(true);
  });

  it('rejects negative maxIterations', () => {
    const result = UserConfigSchema.safeParse({ maxIterations: -1 });
    expect(result.success).toBe(false);
  });

  it('rejects temperature > 2', () => {
    const result = UserConfigSchema.safeParse({ temperature: 2.5 });
    expect(result.success).toBe(false);
  });

  it('rejects temperature < 0', () => {
    const result = UserConfigSchema.safeParse({ temperature: -0.1 });
    expect(result.success).toBe(false);
  });

  it('accepts feature disabled with false', () => {
    const config = {
      planning: false,
      memory: false,
      sandbox: false,
    };
    const result = UserConfigSchema.safeParse(config);
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.planning).toBe(false);
      expect(result.data.memory).toBe(false);
      expect(result.data.sandbox).toBe(false);
    }
  });

  it('accepts feature enabled with object', () => {
    const config = {
      planning: { enabled: true, autoplan: false, maxDepth: 5 },
    };
    const result = UserConfigSchema.safeParse(config);
    expect(result.success).toBe(true);
  });

  it('rejects typos in strict feature sub-schemas', () => {
    const config = {
      planning: { enbled: true }, // typo
    };
    const result = UserConfigSchema.safeParse(config);
    expect(result.success).toBe(false);
  });

  it('passes through unknown top-level keys', () => {
    const config = {
      model: 'gpt-4',
      customExtension: { foo: 'bar' },
    };
    const result = UserConfigSchema.safeParse(config);
    expect(result.success).toBe(true);
    if (result.success) {
      expect((result.data as Record<string, unknown>).customExtension).toEqual({ foo: 'bar' });
    }
  });

  it('accepts providers config', () => {
    const config = {
      providers: { default: 'anthropic' },
    };
    const result = UserConfigSchema.safeParse(config);
    expect(result.success).toBe(true);
  });

  it('accepts provider resilience config', () => {
    const config = {
      providerResilience: {
        enabled: true,
        circuitBreaker: {
          failureThreshold: 3,
          resetTimeout: 60000,
        },
        fallbackProviders: ['openai', 'openrouter'],
        fallbackChain: {
          cooldownMs: 30000,
          failureThreshold: 2,
        },
      },
    };
    const result = UserConfigSchema.safeParse(config);
    expect(result.success).toBe(true);
  });

  it('accepts circuitBreaker: false to disable', () => {
    const config = {
      providerResilience: {
        circuitBreaker: false,
      },
    };
    const result = UserConfigSchema.safeParse(config);
    expect(result.success).toBe(true);
  });

  it('accepts subagent config', () => {
    const config = {
      subagent: {
        enabled: true,
        defaultTimeout: 600000,
        defaultMaxIterations: 20,
      },
    };
    const result = UserConfigSchema.safeParse(config);
    expect(result.success).toBe(true);
  });

  it('accepts compaction config', () => {
    const config = {
      compaction: {
        enabled: true,
        tokenThreshold: 80000,
        mode: 'auto',
      },
    };
    const result = UserConfigSchema.safeParse(config);
    expect(result.success).toBe(true);
  });

  it('accepts resources config with thresholds', () => {
    const config = {
      resources: {
        warnThreshold: 0.8,
        criticalThreshold: 0.95,
      },
    };
    const result = UserConfigSchema.safeParse(config);
    expect(result.success).toBe(true);
  });

  it('rejects warnThreshold > 1', () => {
    const config = {
      resources: {
        warnThreshold: 1.5,
      },
    };
    const result = UserConfigSchema.safeParse(config);
    expect(result.success).toBe(false);
  });

  it('accepts observability config', () => {
    const config = {
      observability: {
        enabled: true,
        tracing: { enabled: false },
        logging: { level: 'warn' },
      },
    };
    const result = UserConfigSchema.safeParse(config);
    expect(result.success).toBe(true);
  });

  it('accepts cancellation config', () => {
    const config = {
      cancellation: {
        defaultTimeout: 0,
        gracePeriod: 10000,
      },
    };
    const result = UserConfigSchema.safeParse(config);
    expect(result.success).toBe(true);
  });
});
