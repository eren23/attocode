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

  it('should honor task.assignedModel failover override when registering worker agent', async () => {
    registeredAgents.clear();

    const config: SwarmConfig = {
      ...DEFAULT_SWARM_CONFIG,
      orchestratorModel: 'test/model',
      workers: [
        { name: 'coder', model: 'test/coder', capabilities: ['code'] },
      ],
    };

    const pool = new SwarmWorkerPool(config, mockAgentRegistry, mockSpawnAgent, mockBudgetPool);

    const task: SwarmTask = {
      id: 'test-3b',
      description: 'Implement parser',
      type: 'implement',
      dependencies: [],
      status: 'ready',
      complexity: 5,
      wave: 0,
      attempts: 1,
      assignedModel: 'failover/model',
    };

    await pool.dispatch(task);

    const registered = registeredAgents.get('swarm-coder-test-3b');
    expect(registered).toBeDefined();
    expect(registered!.model).toBe('failover/model');
    expect(registered!.taskType).toBe('implement');
  });

  it('should pin resolved policy profile for design tasks on coder workers', async () => {
    registeredAgents.clear();

    const config: SwarmConfig = {
      ...DEFAULT_SWARM_CONFIG,
      orchestratorModel: 'test/model',
      workers: [
        { name: 'coder', model: 'test/coder', capabilities: ['code'] },
      ],
    };

    const pool = new SwarmWorkerPool(config, mockAgentRegistry, mockSpawnAgent, mockBudgetPool);

    const task: SwarmTask = {
      id: 'test-3c',
      description: 'Design project structure and shared types',
      type: 'design',
      dependencies: [],
      status: 'ready',
      complexity: 5,
      wave: 0,
      attempts: 0,
    };

    await pool.dispatch(task);

    const registered = registeredAgents.get('swarm-coder-test-3c');
    expect(registered).toBeDefined();
    expect(registered!.policyProfile).toBe('code-strict-bash');
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

  it('should use RESEARCH TASK RULES for research tasks', async () => {
    registeredAgents.clear();

    const config: SwarmConfig = {
      ...DEFAULT_SWARM_CONFIG,
      orchestratorModel: 'test/model',
      workers: [
        { name: 'researcher', model: 'test/researcher', capabilities: ['research'] },
      ],
    };

    const pool = new SwarmWorkerPool(config, mockAgentRegistry, mockSpawnAgent, mockBudgetPool);

    const task: SwarmTask = {
      id: 'test-research',
      description: 'Research React state management options',
      type: 'research',
      dependencies: [],
      status: 'ready',
      complexity: 3,
      wave: 0,
      attempts: 0,
    };

    await pool.dispatch(task);

    const registered = registeredAgents.get('swarm-researcher-test-research');
    expect(registered).toBeDefined();
    expect(registered!.systemPrompt).toContain('RESEARCH TASK RULES');
    expect(registered!.systemPrompt).toContain('You are NOT expected to write or edit code files');
    expect(registered!.systemPrompt).not.toContain('START CODING IMMEDIATELY');
    expect(registered!.systemPrompt).not.toContain('ANTI-LOOP RULES');
  });

  it('should use RESEARCH TASK RULES for analysis tasks', async () => {
    registeredAgents.clear();

    const config: SwarmConfig = {
      ...DEFAULT_SWARM_CONFIG,
      orchestratorModel: 'test/model',
      workers: [
        { name: 'analyst', model: 'test/analyst', capabilities: ['research'] },
      ],
    };

    const pool = new SwarmWorkerPool(config, mockAgentRegistry, mockSpawnAgent, mockBudgetPool);

    const task: SwarmTask = {
      id: 'test-analysis',
      description: 'Analyze codebase architecture',
      type: 'analysis',
      dependencies: [],
      status: 'ready',
      complexity: 4,
      wave: 0,
      attempts: 0,
    };

    await pool.dispatch(task);

    const registered = registeredAgents.get('swarm-analyst-test-analysis');
    expect(registered).toBeDefined();
    expect(registered!.systemPrompt).toContain('RESEARCH TASK RULES');
  });

  it('should use SYNTHESIS TASK RULES for merge tasks', async () => {
    registeredAgents.clear();

    const config: SwarmConfig = {
      ...DEFAULT_SWARM_CONFIG,
      orchestratorModel: 'test/model',
      workers: [
        { name: 'synthesizer', model: 'test/synthesizer', capabilities: ['write', 'code'] },
      ],
    };

    const pool = new SwarmWorkerPool(config, mockAgentRegistry, mockSpawnAgent, mockBudgetPool);

    const task: SwarmTask = {
      id: 'test-merge',
      description: 'Synthesize research findings into recommendation',
      type: 'merge',
      dependencies: ['task-1', 'task-2'],
      status: 'ready',
      complexity: 4,
      wave: 1,
      attempts: 0,
    };

    await pool.dispatch(task);

    const registered = registeredAgents.get('swarm-synthesizer-test-merge');
    expect(registered).toBeDefined();
    expect(registered!.systemPrompt).toContain('SYNTHESIS TASK RULES');
    expect(registered!.systemPrompt).toContain('Do NOT re-research');
    expect(registered!.systemPrompt).toContain('Do NOT run web_search');
    expect(registered!.systemPrompt).not.toContain('START CODING IMMEDIATELY');
    expect(registered!.systemPrompt).not.toContain('ANTI-LOOP RULES');
  });

  it('should use DOCUMENTATION TASK RULES for document tasks', async () => {
    registeredAgents.clear();

    const config: SwarmConfig = {
      ...DEFAULT_SWARM_CONFIG,
      orchestratorModel: 'test/model',
      workers: [
        { name: 'documenter', model: 'test/documenter', capabilities: ['document'] },
      ],
    };

    const pool = new SwarmWorkerPool(config, mockAgentRegistry, mockSpawnAgent, mockBudgetPool);

    const task: SwarmTask = {
      id: 'test-doc',
      description: 'Write API documentation',
      type: 'document',
      dependencies: [],
      status: 'ready',
      complexity: 3,
      wave: 0,
      attempts: 0,
    };

    await pool.dispatch(task);

    const registered = registeredAgents.get('swarm-documenter-test-doc');
    expect(registered).toBeDefined();
    expect(registered!.systemPrompt).toContain('DOCUMENTATION TASK RULES');
    expect(registered!.systemPrompt).not.toContain('START CODING IMMEDIATELY');
  });

  it('should preserve original ANTI-LOOP RULES for code tasks', async () => {
    registeredAgents.clear();

    const config: SwarmConfig = {
      ...DEFAULT_SWARM_CONFIG,
      orchestratorModel: 'test/model',
      workers: [
        { name: 'coder', model: 'test/coder', capabilities: ['code'] },
      ],
    };

    const pool = new SwarmWorkerPool(config, mockAgentRegistry, mockSpawnAgent, mockBudgetPool);

    const task: SwarmTask = {
      id: 'test-code',
      description: 'Implement feature X',
      type: 'implement',
      dependencies: [],
      status: 'ready',
      complexity: 5,
      wave: 0,
      attempts: 0,
    };

    await pool.dispatch(task);

    const registered = registeredAgents.get('swarm-coder-test-code');
    expect(registered).toBeDefined();
    expect(registered!.systemPrompt).toContain('ANTI-LOOP RULES');
    expect(registered!.systemPrompt).toContain('START CODING IMMEDIATELY');
  });

  // ─── V7: Prompt Tier Tests ──────────────────────────────────────────────

  it('should include delegation spec and quality prompt on first attempt (full tier)', async () => {
    registeredAgents.clear();

    const config: SwarmConfig = {
      ...DEFAULT_SWARM_CONFIG,
      orchestratorModel: 'test/model',
      workers: [
        { name: 'coder', model: 'test/coder', capabilities: ['code'] },
      ],
    };

    const pool = new SwarmWorkerPool(config, mockAgentRegistry, mockSpawnAgent, mockBudgetPool);

    const task: SwarmTask = {
      id: 'test-full-tier',
      description: 'Implement feature',
      type: 'implement',
      dependencies: [],
      status: 'ready',
      complexity: 5,
      wave: 0,
      attempts: 0,
    };

    await pool.dispatch(task);

    const registered = registeredAgents.get('swarm-coder-test-full-tier');
    expect(registered).toBeDefined();
    expect(registered!.systemPrompt).toContain('DELEGATION SPEC');
    expect(registered!.systemPrompt).toContain('ENVIRONMENT FACTS');
  });

  it('should skip delegation spec for research tasks even on first attempt', async () => {
    registeredAgents.clear();

    const config: SwarmConfig = {
      ...DEFAULT_SWARM_CONFIG,
      orchestratorModel: 'test/model',
      workers: [
        { name: 'researcher', model: 'test/researcher', capabilities: ['research'] },
      ],
    };

    const pool = new SwarmWorkerPool(config, mockAgentRegistry, mockSpawnAgent, mockBudgetPool);

    const task: SwarmTask = {
      id: 'test-research-no-delegation',
      description: 'Research best practices',
      type: 'research',
      dependencies: [],
      status: 'ready',
      complexity: 3,
      wave: 0,
      attempts: 0,
    };

    await pool.dispatch(task);

    const registered = registeredAgents.get('swarm-researcher-test-research-no-delegation');
    expect(registered).toBeDefined();
    expect(registered!.systemPrompt).toContain('RESEARCH TASK RULES');
    // Research tasks should NOT get delegation spec (redundant)
    expect(registered!.systemPrompt).not.toContain('DELEGATION SPEC');
  });

  it('should use compact facts and skip delegation on retry (reduced tier)', async () => {
    registeredAgents.clear();

    const config: SwarmConfig = {
      ...DEFAULT_SWARM_CONFIG,
      orchestratorModel: 'test/model',
      philosophy: 'Keep it simple.',
      workers: [
        { name: 'coder', model: 'test/coder', capabilities: ['code'] },
      ],
    };

    const pool = new SwarmWorkerPool(config, mockAgentRegistry, mockSpawnAgent, mockBudgetPool);

    const task: SwarmTask = {
      id: 'test-reduced-tier',
      description: 'Implement feature',
      type: 'implement',
      dependencies: [],
      status: 'ready',
      complexity: 5,
      wave: 0,
      attempts: 1, // First retry → reduced tier
      retryContext: {
        previousFeedback: 'No tool calls',
        previousScore: 0,
        attempt: 0,
      },
    };

    await pool.dispatch(task);

    const registered = registeredAgents.get('swarm-coder-test-reduced-tier');
    expect(registered).toBeDefined();
    const prompt = registered!.systemPrompt!;
    // Reduced tier: compact facts (one-liner), no delegation spec, no quality prompt
    expect(prompt).toContain('Current date:'); // compact format
    expect(prompt).not.toContain('ENVIRONMENT FACTS'); // not the full block
    expect(prompt).not.toContain('DELEGATION SPEC');
    expect(prompt).toContain('RETRY CONTEXT'); // retry context is always included
    expect(prompt).toContain('PHILOSOPHY'); // philosophy still included at reduced tier
  });

  it('should use minimal prompt on 2nd+ retry (minimal tier)', async () => {
    registeredAgents.clear();

    const config: SwarmConfig = {
      ...DEFAULT_SWARM_CONFIG,
      orchestratorModel: 'test/model',
      philosophy: 'Be efficient',
      workers: [
        { name: 'coder', model: 'test/coder', capabilities: ['code'] },
      ],
    };

    const pool = new SwarmWorkerPool(config, mockAgentRegistry, mockSpawnAgent, mockBudgetPool);

    const task: SwarmTask = {
      id: 'test-minimal-tier',
      description: 'Implement feature',
      type: 'implement',
      dependencies: [],
      status: 'ready',
      complexity: 5,
      wave: 0,
      attempts: 2, // 2nd retry → minimal tier
      retryContext: {
        previousFeedback: 'Still no tool calls',
        previousScore: 0,
        attempt: 1,
      },
    };

    await pool.dispatch(task);

    const registered = registeredAgents.get('swarm-coder-test-minimal-tier');
    expect(registered).toBeDefined();
    const prompt = registered!.systemPrompt!;
    // Minimal tier: no facts, no delegation, no quality, no philosophy
    expect(prompt).not.toContain('ENVIRONMENT FACTS');
    expect(prompt).not.toContain('Current date:');
    expect(prompt).not.toContain('DELEGATION SPEC');
    expect(prompt).not.toContain('PHILOSOPHY');
    // But still has: worker intro, task rules, retry context
    expect(prompt).toContain('You are a coder worker');
    expect(prompt).toContain('ANTI-LOOP RULES');
    expect(prompt).toContain('RETRY CONTEXT');
  });

  it('should produce shorter prompts on each retry tier', async () => {
    const config: SwarmConfig = {
      ...DEFAULT_SWARM_CONFIG,
      orchestratorModel: 'test/model',
      philosophy: 'Write clean code.',
      workers: [
        { name: 'coder', model: 'test/coder', capabilities: ['code'] },
      ],
    };

    const lengths: number[] = [];
    for (const attempts of [0, 1, 2]) {
      registeredAgents.clear();
      const pool = new SwarmWorkerPool(config, mockAgentRegistry, mockSpawnAgent, mockBudgetPool);

      const task: SwarmTask = {
        id: `test-tier-${attempts}`,
        description: 'Implement feature',
        type: 'implement',
        dependencies: [],
        status: 'ready',
        complexity: 5,
        wave: 0,
        attempts,
        retryContext: attempts > 0 ? {
          previousFeedback: 'Failed',
          previousScore: 0,
          attempt: attempts - 1,
        } : undefined,
      };

      await pool.dispatch(task);
      const registered = registeredAgents.get(`swarm-coder-test-tier-${attempts}`);
      lengths.push(registered!.systemPrompt!.length);
    }

    // Each tier should be shorter than the previous
    expect(lengths[0]).toBeGreaterThan(lengths[1]);
    expect(lengths[1]).toBeGreaterThan(lengths[2]);
  });
});
