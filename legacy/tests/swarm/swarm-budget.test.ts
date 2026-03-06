/**
 * Tests for SwarmBudgetPool
 */
import { describe, it, expect } from 'vitest';
import { createSwarmBudgetPool } from '../../src/integrations/swarm/swarm-budget.js';
import { DEFAULT_SWARM_CONFIG } from '../../src/integrations/swarm/types.js';
import type { SwarmConfig } from '../../src/integrations/swarm/types.js';

const config: SwarmConfig = {
  ...DEFAULT_SWARM_CONFIG,
  orchestratorModel: 'test/model',
  workers: [],
};

describe('createSwarmBudgetPool', () => {
  it('should create pool with correct orchestrator reserve', () => {
    const budget = createSwarmBudgetPool(config);

    // Default: 15% of 5M = 750K
    expect(budget.orchestratorReserve).toBe(750000);
  });

  it('should set max per worker from config', () => {
    const budget = createSwarmBudgetPool(config);
    expect(budget.maxPerWorker).toBe(50000);
  });

  it('should report capacity', () => {
    const budget = createSwarmBudgetPool(config);
    expect(budget.hasCapacity()).toBe(true);
  });

  it('should get stats from underlying pool', () => {
    const budget = createSwarmBudgetPool(config);
    const stats = budget.getStats();

    expect(stats.totalTokens).toBeGreaterThan(0);
    expect(stats.tokensUsed).toBe(0);
  });

  it('should allocate budget for workers', () => {
    const budget = createSwarmBudgetPool(config);

    // Reserve for a worker
    const allocation = budget.pool.reserve('worker-1');
    expect(allocation).not.toBeNull();
    expect(allocation!.tokenBudget).toBeLessThanOrEqual(config.maxTokensPerWorker);
  });

  it('should respect custom config values', () => {
    const customConfig: SwarmConfig = {
      ...config,
      totalBudget: 5_000_000,
      orchestratorReserveRatio: 0.20,
      maxTokensPerWorker: 50000,
    };

    const budget = createSwarmBudgetPool(customConfig);

    expect(budget.orchestratorReserve).toBe(1_000_000); // 20% of 5M
    expect(budget.maxPerWorker).toBe(50000);
  });
});
