/**
 * Tests for enhanced worker prompts and tool access
 */
import { describe, it, expect, vi } from 'vitest';
import { SwarmWorkerPool } from '../../src/integrations/swarm/worker-pool.js';
import { DEFAULT_SWARM_CONFIG } from '../../src/integrations/swarm/types.js';
import type { SwarmConfig, SwarmTask } from '../../src/integrations/swarm/types.js';
import type { AgentRegistry, AgentDefinition } from '../../src/integrations/agent-registry.js';
import type { SwarmBudgetPool } from '../../src/integrations/swarm/swarm-budget.js';

// Capture registered agent definitions
const registeredAgents = new Map<string, AgentDefinition>();

const mockAgentRegistry = {
  registerAgent: vi.fn((def: AgentDefinition) => {
    registeredAgents.set(def.name, def);
  }),
  unregisterAgent: vi.fn(),
  getAgent: vi.fn(),
  listAgents: vi.fn(() => []),
  filterToolsForAgent: vi.fn(() => []),
} as unknown as AgentRegistry;

const mockSpawnAgent = vi.fn().mockResolvedValue({
  success: true,
  output: 'Done',
  metrics: { tokens: 100, duration: 1000, toolCalls: 0 },
});

const mockBudgetPool = {
  hasCapacity: vi.fn().mockReturnValue(true),
  pool: { reserve: vi.fn().mockReturnValue({ tokenBudget: 50000 }) },
  orchestratorReserve: 750000,
  maxPerWorker: 50000,
  getStats: vi.fn().mockReturnValue({ totalTokens: 5000000, tokensUsed: 0 }),
} as unknown as SwarmBudgetPool;

describe('Worker prompts', () => {
  it('should include anti-loop rules in system prompt', async () => {
    const config: SwarmConfig = {
      ...DEFAULT_SWARM_CONFIG,
      orchestratorModel: 'test/model',
      workers: [
        { name: 'coder', model: 'test/coder', capabilities: ['code', 'test'] },
      ],
    };

    const pool = new SwarmWorkerPool(config, mockAgentRegistry, mockSpawnAgent, mockBudgetPool);

    const task: SwarmTask = {
      id: 'test-1',
      description: 'Implement parser',
      type: 'implement',
      dependencies: [],
      status: 'ready',
      complexity: 5,
      wave: 0,
      attempts: 0,
    };

    await pool.dispatch(task);

    const registered = registeredAgents.get('swarm-coder-test-1');
    expect(registered).toBeDefined();
    expect(registered!.systemPrompt).toContain('ANTI-LOOP RULES');
    expect(registered!.systemPrompt).toContain('Never run ls');
    expect(registered!.systemPrompt).toContain('START CODING IMMEDIATELY');
    expect(registered!.systemPrompt).toContain('Do NOT run ls/find/tree');
  });

  it('should set tools to undefined when toolAccessMode is all', async () => {
    registeredAgents.clear();

    const config: SwarmConfig = {
      ...DEFAULT_SWARM_CONFIG,
      orchestratorModel: 'test/model',
      toolAccessMode: 'all',
      workers: [
        { name: 'coder', model: 'test/coder', capabilities: ['code'], allowedTools: ['read_file', 'write_file'] },
      ],
    };

    const pool = new SwarmWorkerPool(config, mockAgentRegistry, mockSpawnAgent, mockBudgetPool);

    const task: SwarmTask = {
      id: 'test-2',
      description: 'Implement parser',
      type: 'implement',
      dependencies: [],
      status: 'ready',
      complexity: 5,
      wave: 0,
      attempts: 0,
    };

    await pool.dispatch(task);

    const registered = registeredAgents.get('swarm-coder-test-2');
    expect(registered).toBeDefined();
    // In 'all' mode, tools should be undefined (giving access to ALL tools including MCP)
    expect(registered!.tools).toBeUndefined();
  });

  it('should use whitelist when toolAccessMode is whitelist', async () => {
    registeredAgents.clear();

    const config: SwarmConfig = {
      ...DEFAULT_SWARM_CONFIG,
      orchestratorModel: 'test/model',
      toolAccessMode: 'whitelist',
      workers: [
        { name: 'coder', model: 'test/coder', capabilities: ['code'], allowedTools: ['read_file', 'write_file'] },
      ],
    };

    const pool = new SwarmWorkerPool(config, mockAgentRegistry, mockSpawnAgent, mockBudgetPool);

    const task: SwarmTask = {
      id: 'test-3',
      description: 'Implement parser',
      type: 'implement',
      dependencies: [],
      status: 'ready',
      complexity: 5,
      wave: 0,
      attempts: 0,
    };

    await pool.dispatch(task);

    const registered = registeredAgents.get('swarm-coder-test-3');
    expect(registered).toBeDefined();
    expect(registered!.tools).toEqual(['read_file', 'write_file']);
  });

  it('should inject worker persona into system prompt', async () => {
    registeredAgents.clear();

    const config: SwarmConfig = {
      ...DEFAULT_SWARM_CONFIG,
      orchestratorModel: 'test/model',
      workers: [
        { name: 'coder', model: 'test/coder', capabilities: ['code'], persona: 'You are a senior TypeScript expert.' },
      ],
    };

    const pool = new SwarmWorkerPool(config, mockAgentRegistry, mockSpawnAgent, mockBudgetPool);

    const task: SwarmTask = {
      id: 'test-persona',
      description: 'Add types',
      type: 'implement',
      dependencies: [],
      status: 'ready',
      complexity: 3,
      wave: 0,
      attempts: 0,
    };

    await pool.dispatch(task);

    const registered = registeredAgents.get('swarm-coder-test-persona');
    expect(registered).toBeDefined();
    expect(registered!.systemPrompt).toContain('You are a senior TypeScript expert.');
    // Persona should appear before the worker intro
    const personaIdx = registered!.systemPrompt!.indexOf('senior TypeScript expert');
    const workerIdx = registered!.systemPrompt!.indexOf('You are a coder worker');
    expect(personaIdx).toBeLessThan(workerIdx);
  });

  it('should inject philosophy into system prompt', async () => {
    registeredAgents.clear();

    const config: SwarmConfig = {
      ...DEFAULT_SWARM_CONFIG,
      orchestratorModel: 'test/model',
      philosophy: 'Write clean, tested code. Prefer simplicity.',
      workers: [
        { name: 'coder', model: 'test/coder', capabilities: ['code'] },
      ],
    };

    const pool = new SwarmWorkerPool(config, mockAgentRegistry, mockSpawnAgent, mockBudgetPool);

    const task: SwarmTask = {
      id: 'test-philosophy',
      description: 'Refactor module',
      type: 'refactor',
      dependencies: [],
      status: 'ready',
      complexity: 5,
      wave: 0,
      attempts: 0,
    };

    await pool.dispatch(task);

    const registered = registeredAgents.get('swarm-coder-test-philosophy');
    expect(registered).toBeDefined();
    expect(registered!.systemPrompt).toContain('PHILOSOPHY');
    expect(registered!.systemPrompt).toContain('Write clean, tested code');
  });

  it('should include worker role in system prompt', async () => {
    registeredAgents.clear();

    const config: SwarmConfig = {
      ...DEFAULT_SWARM_CONFIG,
      orchestratorModel: 'test/model',
      workers: [
        { name: 'coder', model: 'test/coder', capabilities: ['code'], role: 'executor' },
      ],
    };

    const pool = new SwarmWorkerPool(config, mockAgentRegistry, mockSpawnAgent, mockBudgetPool);

    const task: SwarmTask = {
      id: 'test-role',
      description: 'Implement feature',
      type: 'implement',
      dependencies: [],
      status: 'ready',
      complexity: 3,
      wave: 0,
      attempts: 0,
    };

    await pool.dispatch(task);

    const registered = registeredAgents.get('swarm-coder-test-role');
    expect(registered).toBeDefined();
    expect(registered!.systemPrompt).toContain('(executor)');
  });
});
