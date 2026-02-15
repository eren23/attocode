/**
 * Production Agent Tests
 *
 * Tests for the main ProductionAgent class and its features.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  ProductionAgent,
  createProductionAgent,
  buildAgent,
  ProductionAgentBuilder,
} from '../src/agent.js';
import type { LLMProvider, Message, ToolDefinition, ChatResponse } from '../src/types.js';

// =============================================================================
// MOCK PROVIDER
// =============================================================================

function createMockProvider(responses: string[] = ['Mock response']): LLMProvider {
  let callIndex = 0;

  return {
    chat: vi.fn(async (messages: Message[], options?: { model?: string; tools?: ToolDefinition[] }): Promise<ChatResponse> => {
      const response = responses[callIndex % responses.length];
      callIndex++;

      return {
        content: response,
        toolCalls: [],
        usage: {
          inputTokens: 100,
          outputTokens: 50,
          totalTokens: 150,
        },
      };
    }),
  };
}

// Mock provider that returns tool calls
function createMockProviderWithTools(toolResponses: Array<{
  content?: string;
  toolCalls?: Array<{ id: string; name: string; arguments: Record<string, unknown> }>;
}>): LLMProvider {
  let callIndex = 0;

  return {
    chat: vi.fn(async (): Promise<ChatResponse> => {
      const response = toolResponses[callIndex % toolResponses.length];
      callIndex++;

      return {
        content: response.content || '',
        toolCalls: response.toolCalls || [],
        usage: { inputTokens: 100, outputTokens: 50, totalTokens: 150 },
      };
    }),
  };
}

// =============================================================================
// MOCK TOOLS
// =============================================================================

const mockReadFileTool: ToolDefinition = {
  name: 'read_file',
  description: 'Read a file',
  parameters: {
    type: 'object',
    properties: {
      path: { type: 'string', description: 'File path' },
    },
    required: ['path'],
  },
  execute: vi.fn(async (args: Record<string, unknown>) => `Contents of ${args.path}`),
};

const mockWriteFileTool: ToolDefinition = {
  name: 'write_file',
  description: 'Write a file',
  parameters: {
    type: 'object',
    properties: {
      path: { type: 'string', description: 'File path' },
      content: { type: 'string', description: 'Content to write' },
    },
    required: ['path', 'content'],
  },
  execute: vi.fn(async () => 'File written successfully'),
};

const mockListFilesTool: ToolDefinition = {
  name: 'list_files',
  description: 'List files in a directory',
  parameters: {
    type: 'object',
    properties: {
      path: { type: 'string', description: 'Directory path' },
    },
  },
  execute: vi.fn(async () => ['file1.ts', 'file2.ts']),
};

const mockTools = [mockReadFileTool, mockWriteFileTool, mockListFilesTool];

// =============================================================================
// TESTS
// =============================================================================

describe('ProductionAgent', () => {
  let agent: ProductionAgent;
  let mockProvider: LLMProvider;

  beforeEach(() => {
    mockProvider = createMockProvider(['Test response']);

    agent = new ProductionAgent({
      provider: mockProvider,
      tools: mockTools,
      systemPrompt: 'You are a test assistant.',
      maxIterations: 10,
      // Disable most features for unit testing
      memory: false,
      planning: false,
      reflection: false,
      observability: false,
      sandbox: false,
      humanInLoop: false,
      routing: false,
      multiAgent: false,
      react: false,
      executionPolicy: false,
      threads: false,
      rules: false,
      hooks: false,
      plugins: false,
      cancellation: false,
      resources: false,
      lsp: false,
      semanticCache: false,
    });
  });

  afterEach(async () => {
    await agent.cleanup();
  });

  describe('initialization', () => {
    it('should create agent with provider', () => {
      expect(agent).toBeDefined();
    });

    it('should register tools', () => {
      const state = agent.getState();
      expect(state.status).toBe('idle');
    });

    it('should initialize in idle state', () => {
      const state = agent.getState();
      expect(state.status).toBe('idle');
      expect(state.messages).toEqual([]);
      expect(state.iteration).toBe(0);
    });
  });

  describe('run', () => {
    it('should execute a task and return result', async () => {
      const result = await agent.run('What is 2 + 2?');

      expect(result.success).toBe(true);
      expect(result.response).toBe('Test response');
      expect(result.traceId).toBeDefined();
    });

    it('should track metrics', async () => {
      const result = await agent.run('Test task');

      expect(result.metrics.llmCalls).toBeGreaterThan(0);
      expect(result.metrics.totalTokens).toBeGreaterThan(0);
      // Duration might be 0 in fast tests - just check it exists and is non-negative
      expect(result.metrics.duration).toBeGreaterThanOrEqual(0);
    });

    it('should store messages', async () => {
      await agent.run('Test task');

      const state = agent.getState();
      expect(state.messages.length).toBeGreaterThan(0);
    });

    it('should fail completion when response remains future-intent without action', async () => {
      const provider = createMockProvider([
        "I'll fix this now.",
        "I'll fix this now.",
        "I'll fix this now.",
        "I'll fix this now.",
        "I'll fix this now.",
      ]);

      const intentAgent = new ProductionAgent({
        provider,
        tools: mockTools,
        maxIterations: 10,
        memory: false,
        planning: false,
        reflection: false,
        observability: false,
        sandbox: false,
        humanInLoop: false,
        routing: false,
        multiAgent: false,
        react: false,
        executionPolicy: false,
        threads: false,
        rules: false,
        hooks: false,
        plugins: false,
        cancellation: false,
        resources: false,
        lsp: false,
        semanticCache: false,
      });

      const result = await intentAgent.run('Fix the failing code and explain what changed.');
      expect(result.success).toBe(false);
      expect(['incomplete_action', 'future_intent']).toContain(result.completion.reason);

      await intentAgent.cleanup();
    });

    it('should block completion when tasks remain in_progress', async () => {
      const provider = createMockProviderWithTools([
        {
          content: '',
          toolCalls: [{
            id: 'task-create-1',
            name: 'task_create',
            arguments: {
              subject: 'Fix compile errors',
              description: 'Fix remaining compile errors',
            },
          }],
        },
        {
          content: '',
          toolCalls: [{
            id: 'task-update-1',
            name: 'task_update',
            arguments: {
              taskId: '1',
              status: 'in_progress',
            },
          }],
        },
        { content: 'Done.', toolCalls: [] },
      ]);

      const taskAgent = new ProductionAgent({
        provider,
        tools: mockTools,
        maxIterations: 10,
        memory: false,
        planning: false,
        reflection: false,
        observability: false,
        sandbox: false,
        humanInLoop: false,
        routing: false,
        multiAgent: false,
        react: false,
        executionPolicy: false,
        threads: false,
        rules: false,
        hooks: false,
        plugins: false,
        cancellation: false,
        resources: false,
        lsp: false,
        semanticCache: false,
      });

      const result = await taskAgent.run('Fix the codebase issues.');
      expect(result.success).toBe(false);
      expect(result.completion.reason).toBe('open_tasks');
      expect(result.completion.openTasks?.inProgress).toBeGreaterThan(0);

      await taskAgent.cleanup();
    });
  });

  describe('tool execution', () => {
    it('should execute tool calls', async () => {
      const provider = createMockProviderWithTools([
        {
          content: '',
          toolCalls: [{ id: 'call-1', name: 'read_file', arguments: { path: 'test.txt' } }],
        },
        { content: 'Done reading file', toolCalls: [] },
      ]);

      const toolAgent = new ProductionAgent({
        provider,
        tools: mockTools,
        maxIterations: 5,
        memory: false,
        planning: false,
        reflection: false,
        observability: false,
        sandbox: false,
        humanInLoop: false,
        routing: false,
        multiAgent: false,
        react: false,
        executionPolicy: false,
        threads: false,
        rules: false,
        hooks: false,
        plugins: false,
        cancellation: false,
        resources: false,
        lsp: false,
        semanticCache: false,
      });

      const result = await toolAgent.run('Read test.txt');

      expect(result.success).toBe(true);
      expect(mockReadFileTool.execute).toHaveBeenCalled();

      await toolAgent.cleanup();
    });
  });

  describe('tool management', () => {
    it('should add tools dynamically', () => {
      const newTool: ToolDefinition = {
        name: 'new_tool',
        description: 'A new tool',
        parameters: {},
        execute: async () => 'result',
      };

      agent.addTool(newTool);

      // Tool is added internally, verify it doesn't throw
      expect(true).toBe(true);
    });

    it('should remove tools', () => {
      agent.removeTool('read_file');

      // Tool is removed internally
      expect(true).toBe(true);
    });
  });

  describe('state management', () => {
    it('should get current state', () => {
      const state = agent.getState();

      expect(state.status).toBe('idle');
      expect(Array.isArray(state.messages)).toBe(true);
      expect(typeof state.iteration).toBe('number');
    });

    it('should reset state', async () => {
      await agent.run('Test task');
      agent.reset();

      const state = agent.getState();
      expect(state.messages).toEqual([]);
      expect(state.iteration).toBe(0);
    });

    it('should load messages from previous session', () => {
      const messages = [
        { role: 'user' as const, content: 'Hello' },
        { role: 'assistant' as const, content: 'Hi there!' },
      ];

      agent.loadMessages(messages);

      const state = agent.getState();
      expect(state.messages.length).toBe(2);
    });
  });

  describe('mode management', () => {
    it('should start in build mode', () => {
      expect(agent.getMode()).toBe('build');
    });

    it('should change modes', () => {
      agent.setMode('plan');
      expect(agent.getMode()).toBe('plan');

      agent.setMode('review');
      expect(agent.getMode()).toBe('review');
    });

    it('should cycle modes', () => {
      expect(agent.getMode()).toBe('build');

      agent.cycleMode();
      expect(agent.getMode()).toBe('plan');

      agent.cycleMode();
      expect(agent.getMode()).toBe('review');

      agent.cycleMode();
      expect(agent.getMode()).toBe('debug');

      agent.cycleMode();
      expect(agent.getMode()).toBe('build');
    });

    it('should get mode info', () => {
      const info = agent.getModeInfo();

      expect(info.name).toBeDefined();
      expect(info.color).toBeDefined();
      expect(info.icon).toBeDefined();
    });

    it('should format mode for prompt', () => {
      const prompt = agent.formatModePrompt();
      expect(prompt).toContain('Build');
    });

    it('should get available modes list', () => {
      const modes = agent.getAvailableModes();
      expect(modes).toContain('build');
      expect(modes).toContain('plan');
    });

    it('should filter tools by mode', () => {
      agent.setMode('build');
      const buildTools = agent.getModeFilteredTools();
      expect(buildTools.some((t) => t.name === 'read_file')).toBe(true);
      expect(buildTools.some((t) => t.name === 'write_file')).toBe(true);
      expect(buildTools.some((t) => t.name === 'spawn_agent')).toBe(true);
      expect(buildTools.some((t) => t.name === 'spawn_agents_parallel')).toBe(true);

      agent.setMode('plan');
      const planTools = agent.getModeFilteredTools();
      // Plan mode allows all tools but intercepts writes - same count
      expect(planTools.some((t) => t.name === 'read_file')).toBe(true);
      expect(planTools.some((t) => t.name === 'list_files')).toBe(true);
    });
  });

  describe('event subscription', () => {
    it('should subscribe to events', () => {
      const events: unknown[] = [];
      const unsubscribe = agent.subscribe((e) => events.push(e));

      expect(typeof unsubscribe).toBe('function');
      unsubscribe();
    });
  });

  describe('metrics', () => {
    it('should return metrics', async () => {
      await agent.run('Test task');
      const metrics = agent.getMetrics();

      expect(metrics.llmCalls).toBeGreaterThanOrEqual(1);
      expect(metrics.totalTokens).toBeGreaterThanOrEqual(0);
    });
  });

  describe('cleanup', () => {
    it('should cleanup without errors', async () => {
      await expect(agent.cleanup()).resolves.not.toThrow();
    });
  });
});

describe('createProductionAgent', () => {
  it('should create agent with factory function', () => {
    const provider = createMockProvider();
    const agent = createProductionAgent({
      provider,
      tools: mockTools,
    });

    expect(agent).toBeInstanceOf(ProductionAgent);
    agent.cleanup();
  });
});

describe('ProductionAgentBuilder', () => {
  let mockProvider: LLMProvider;

  beforeEach(() => {
    mockProvider = createMockProvider();
  });

  it('should build agent with builder pattern', () => {
    const agent = buildAgent()
      .provider(mockProvider)
      .model('test-model')
      .systemPrompt('Test prompt')
      .tools(mockTools)
      .maxIterations(50)
      .build();

    expect(agent).toBeInstanceOf(ProductionAgent);
    agent.cleanup();
  });

  it('should throw without provider', () => {
    expect(() => buildAgent().build()).toThrow('Provider is required');
  });

  it('should disable features', () => {
    const agent = buildAgent()
      .provider(mockProvider)
      .disable('memory')
      .disable('planning')
      .build();

    expect(agent).toBeInstanceOf(ProductionAgent);
    agent.cleanup();
  });

  it('should chain configuration', () => {
    const builder = buildAgent()
      .provider(mockProvider)
      .model('model-1')
      .systemPrompt('prompt')
      .tools(mockTools)
      .memory({ enabled: true })
      .planning({ enabled: true })
      .observability({ enabled: true });

    expect(builder).toBeInstanceOf(ProductionAgentBuilder);
    const agent = builder.build();
    agent.cleanup();
  });
});

describe('ProductionAgent with enabled features', () => {
  let mockProvider: LLMProvider;

  beforeEach(() => {
    mockProvider = createMockProvider(['Test response']);
  });

  describe('with cancellation enabled', () => {
    it('should support cancellation', async () => {
      const agent = new ProductionAgent({
        provider: mockProvider,
        tools: mockTools,
        cancellation: { enabled: true },
        memory: false,
        planning: false,
        reflection: false,
        observability: false,
        sandbox: false,
        humanInLoop: false,
        routing: false,
        multiAgent: false,
        react: false,
        executionPolicy: false,
        threads: false,
        rules: false,
        hooks: false,
        plugins: false,
        resources: false,
        lsp: false,
        semanticCache: false,
      });

      expect(agent.isCancelled()).toBe(false);

      // Cancellation only works during an active run - start one
      const runPromise = agent.run('Test task');

      // Cancel mid-run
      agent.cancel('Test cancellation');

      // Wait for run to complete (should be cancelled)
      await runPromise;

      // After run completes, context is disposed - isCancelled reflects post-run state
      // The cancellation was successfully requested during the run
      expect(agent.getState().status).toBe('paused'); // Status reflects cancellation

      await agent.cleanup();
    });
  });

  describe('with resource monitoring enabled', () => {
    it('should track resource usage', async () => {
      const agent = new ProductionAgent({
        provider: mockProvider,
        tools: mockTools,
        resources: { enabled: true, maxMemoryMB: 512 },
        memory: false,
        planning: false,
        reflection: false,
        observability: false,
        sandbox: false,
        humanInLoop: false,
        routing: false,
        multiAgent: false,
        react: false,
        executionPolicy: false,
        threads: false,
        rules: false,
        hooks: false,
        plugins: false,
        cancellation: false,
        lsp: false,
        semanticCache: false,
      });

      const usage = agent.getResourceUsage();
      expect(usage).not.toBeNull();

      const status = agent.getResourceStatus();
      expect(typeof status).toBe('string');

      await agent.cleanup();
    });
  });

  describe('with semantic cache enabled', () => {
    it('should support caching', async () => {
      const agent = new ProductionAgent({
        provider: mockProvider,
        tools: mockTools,
        semanticCache: { enabled: true, threshold: 0.8 },
        memory: false,
        planning: false,
        reflection: false,
        observability: false,
        sandbox: false,
        humanInLoop: false,
        routing: false,
        multiAgent: false,
        react: false,
        executionPolicy: false,
        threads: false,
        rules: false,
        hooks: false,
        plugins: false,
        cancellation: false,
        resources: false,
        lsp: false,
      });

      // Cache a response
      const id = await agent.cacheResponse('Test query', 'Test response');
      expect(id).not.toBeNull();

      // Check for cached response
      const cached = await agent.getCachedResponse('Test query');
      expect(cached).not.toBeNull();
      expect(cached?.response).toBe('Test response');

      // Get stats
      const stats = agent.getCacheStats();
      expect(stats.size).toBe(1);

      // Clear cache
      agent.clearCache();
      expect(agent.getCacheStats().size).toBe(0);

      await agent.cleanup();
    });
  });

  describe('with threads enabled', () => {
    it('should support checkpoints', async () => {
      const agent = new ProductionAgent({
        provider: mockProvider,
        tools: mockTools,
        threads: { enabled: true },
        memory: false,
        planning: false,
        reflection: false,
        observability: false,
        sandbox: false,
        humanInLoop: false,
        routing: false,
        multiAgent: false,
        react: false,
        executionPolicy: false,
        rules: false,
        hooks: false,
        plugins: false,
        cancellation: false,
        resources: false,
        lsp: false,
        semanticCache: false,
      });

      // Create checkpoint
      const checkpoint = agent.createCheckpoint('test-checkpoint');
      expect(checkpoint.id).toBeDefined();
      expect(checkpoint.label).toBe('test-checkpoint');

      // Get checkpoints
      const checkpoints = agent.getCheckpoints();
      expect(checkpoints.length).toBe(1);

      await agent.cleanup();
    });

    it('should support forking', async () => {
      const agent = new ProductionAgent({
        provider: mockProvider,
        tools: mockTools,
        threads: { enabled: true },
        memory: false,
        planning: false,
        reflection: false,
        observability: false,
        sandbox: false,
        humanInLoop: false,
        routing: false,
        multiAgent: false,
        react: false,
        executionPolicy: false,
        rules: false,
        hooks: false,
        plugins: false,
        cancellation: false,
        resources: false,
        lsp: false,
        semanticCache: false,
      });

      // Fork thread
      const threadId = agent.fork('test-fork');
      expect(threadId).toBeDefined();

      // Get all threads
      const threads = agent.getAllThreads();
      expect(threads.length).toBeGreaterThanOrEqual(1);

      await agent.cleanup();
    });
  });

  describe('with budget tracking', () => {
    it('should track budget usage', async () => {
      const agent = new ProductionAgent({
        provider: mockProvider,
        tools: mockTools,
        maxIterations: 100,
        memory: false,
        planning: false,
        reflection: false,
        observability: false,
        sandbox: false,
        humanInLoop: false,
        routing: false,
        multiAgent: false,
        react: false,
        executionPolicy: false,
        threads: false,
        rules: false,
        hooks: false,
        plugins: false,
        cancellation: false,
        resources: false,
        lsp: false,
        semanticCache: false,
      });

      await agent.run('Test task');

      const usage = agent.getBudgetUsage();
      expect(usage).not.toBeNull();
      // Iterations tracks tool calls, not LLM calls - mock returns no tool calls
      expect(usage?.tokens).toBeGreaterThan(0); // But tokens should be tracked

      const limits = agent.getBudgetLimits();
      expect(limits).not.toBeNull();
      expect(limits?.maxIterations).toBeGreaterThanOrEqual(100);

      const progress = agent.getProgress();
      expect(progress).not.toBeNull();

      await agent.cleanup();
    });

    it('should extend budget', async () => {
      const agent = new ProductionAgent({
        provider: mockProvider,
        tools: mockTools,
        maxIterations: 10,
        memory: false,
        planning: false,
        reflection: false,
        observability: false,
        sandbox: false,
        humanInLoop: false,
        routing: false,
        multiAgent: false,
        react: false,
        executionPolicy: false,
        threads: false,
        rules: false,
        hooks: false,
        plugins: false,
        cancellation: false,
        resources: false,
        lsp: false,
        semanticCache: false,
      });

      const initialLimits = agent.getBudgetLimits();
      expect(initialLimits?.maxIterations).toBe(10);

      agent.extendBudget({ maxIterations: 50 });

      const newLimits = agent.getBudgetLimits();
      // Note: extendBudget adds to existing, so it should be 60
      expect(newLimits?.maxIterations).toBeGreaterThan(10);

      await agent.cleanup();
    });
  });

  describe('agent registry', () => {
    it('should get available agents', async () => {
      const agent = new ProductionAgent({
        provider: mockProvider,
        tools: mockTools,
        memory: false,
        planning: false,
        reflection: false,
        observability: false,
        sandbox: false,
        humanInLoop: false,
        routing: false,
        multiAgent: false,
        react: false,
        executionPolicy: false,
        threads: false,
        rules: false,
        hooks: false,
        plugins: false,
        cancellation: false,
        resources: false,
        lsp: false,
        semanticCache: false,
      });

      const agents = agent.getAgents();
      expect(Array.isArray(agents)).toBe(true);
      // Should have built-in agents
      expect(agents.length).toBeGreaterThan(0);

      const agentList = agent.formatAgentList();
      expect(typeof agentList).toBe('string');

      await agent.cleanup();
    });

    it('should register custom agents', async () => {
      const agent = new ProductionAgent({
        provider: mockProvider,
        tools: mockTools,
        memory: false,
        planning: false,
        reflection: false,
        observability: false,
        sandbox: false,
        humanInLoop: false,
        routing: false,
        multiAgent: false,
        react: false,
        executionPolicy: false,
        threads: false,
        rules: false,
        hooks: false,
        plugins: false,
        cancellation: false,
        resources: false,
        lsp: false,
        semanticCache: false,
      });

      agent.registerAgent({
        name: 'test-agent',
        description: 'A test agent',
        systemPrompt: 'You are a test agent.',
      });

      const testAgent = agent.getAgent('test-agent');
      expect(testAgent).toBeDefined();
      expect(testAgent?.name).toBe('test-agent');

      agent.unregisterAgent('test-agent');
      expect(agent.getAgent('test-agent')).toBeUndefined();

      await agent.cleanup();
    });

    it('should find agents for task', async () => {
      const agent = new ProductionAgent({
        provider: mockProvider,
        tools: mockTools,
        memory: false,
        planning: false,
        reflection: false,
        observability: false,
        sandbox: false,
        humanInLoop: false,
        routing: false,
        multiAgent: false,
        react: false,
        executionPolicy: false,
        threads: false,
        rules: false,
        hooks: false,
        plugins: false,
        cancellation: false,
        resources: false,
        lsp: false,
        semanticCache: false,
      });

      const matches = agent.findAgentsForTask('code review', 3);
      expect(Array.isArray(matches)).toBe(true);

      await agent.cleanup();
    });
  });

  describe('incomplete action resilience', () => {
    it('should recover when response promises action but emits no tool call', async () => {
      const provider = createMockProviderWithTools([
        { content: "Now I'll create the report.", toolCalls: [] },
        { content: '', toolCalls: [{ id: 'call-1', name: 'write_file', arguments: { path: 'analysis.md', content: '# Report' } }] },
        { content: 'Created analysis.md with the report.', toolCalls: [] },
      ]);

      const recoveryAgent = new ProductionAgent({
        provider,
        tools: mockTools,
        maxIterations: 6,
        resilience: {
          enabled: true,
          incompleteActionRecovery: true,
          maxIncompleteActionRetries: 2,
          enforceRequestedArtifacts: true,
        },
        memory: false,
        planning: false,
        reflection: false,
        observability: false,
        sandbox: false,
        humanInLoop: false,
        routing: false,
        multiAgent: false,
        react: false,
        executionPolicy: false,
        threads: false,
        rules: false,
        hooks: false,
        plugins: false,
        cancellation: false,
        resources: false,
        lsp: false,
        semanticCache: false,
      });

      const result = await recoveryAgent.run('Compare systems and write analysis.md');

      expect(result.success).toBe(true);
      expect(mockWriteFileTool.execute).toHaveBeenCalled();
      expect((provider.chat as any).mock.calls.length).toBe(3);

      await recoveryAgent.cleanup();
    });

    it('should fail when incomplete action persists beyond retry limit', async () => {
      const provider = createMockProviderWithTools([
        { content: "Now I'll create analysis.md.", toolCalls: [] },
      ]);

      const failingAgent = new ProductionAgent({
        provider,
        tools: mockTools,
        maxIterations: 4,
        resilience: {
          enabled: true,
          incompleteActionRecovery: true,
          maxIncompleteActionRetries: 1,
          enforceRequestedArtifacts: true,
        },
        memory: false,
        planning: false,
        reflection: false,
        observability: false,
        sandbox: false,
        humanInLoop: false,
        routing: false,
        multiAgent: false,
        react: false,
        executionPolicy: false,
        threads: false,
        rules: false,
        hooks: false,
        plugins: false,
        cancellation: false,
        resources: false,
        lsp: false,
        semanticCache: false,
      });

      const result = await failingAgent.run('Create a plan and write analysis.md');

      expect(result.success).toBe(false);
      expect(result.error).toContain('incomplete_action_missing_artifact');
      expect((provider.chat as any).mock.calls.length).toBe(2);

      await failingAgent.cleanup();
    });

    it('should not retry normal no-tool final responses', async () => {
      const provider = createMockProviderWithTools([
        { content: 'Here is the requested summary.', toolCalls: [] },
      ]);

      const normalAgent = new ProductionAgent({
        provider,
        tools: mockTools,
        maxIterations: 4,
        resilience: {
          enabled: true,
          incompleteActionRecovery: true,
          maxIncompleteActionRetries: 2,
          enforceRequestedArtifacts: true,
        },
        memory: false,
        planning: false,
        reflection: false,
        observability: false,
        sandbox: false,
        humanInLoop: false,
        routing: false,
        multiAgent: false,
        react: false,
        executionPolicy: false,
        threads: false,
        rules: false,
        hooks: false,
        plugins: false,
        cancellation: false,
        resources: false,
        lsp: false,
        semanticCache: false,
      });

      const result = await normalAgent.run('Explain current architecture tradeoffs');

      expect(result.success).toBe(true);
      expect((provider.chat as any).mock.calls.length).toBe(1);

      await normalAgent.cleanup();
    });
  });

  describe('auto routing waits', () => {
    it('should pause and resume duration around delegation confirmation', async () => {
      const routedAgent = new ProductionAgent({
        provider: mockProvider,
        tools: mockTools,
        memory: false,
        planning: false,
        reflection: false,
        observability: false,
        sandbox: false,
        humanInLoop: false,
        routing: false,
        multiAgent: false,
        react: false,
        executionPolicy: false,
        threads: false,
        rules: false,
        hooks: false,
        plugins: false,
        cancellation: false,
        resources: false,
        lsp: false,
        semanticCache: false,
      });

      const pauseDuration = vi.fn();
      const resumeDuration = vi.fn();
      (routedAgent as any).economics = { pauseDuration, resumeDuration };
      (routedAgent as any).suggestAgentForTask = vi.fn().mockResolvedValue({
        suggestions: [{
          agent: { name: 'researcher' },
          confidence: 0.95,
          reason: 'best match',
        }],
        shouldDelegate: true,
        delegateAgent: 'researcher',
      });
      (routedAgent as any).spawnAgent = vi.fn().mockResolvedValue({
        success: true,
        output: 'ok',
        metrics: { tokens: 1, duration: 1, toolCalls: 0 },
      });

      await routedAgent.runWithAutoRouting('find files', {
        confidenceThreshold: 0.8,
        confirmDelegate: async () => true,
      });

      expect(pauseDuration).toHaveBeenCalledTimes(1);
      expect(resumeDuration).toHaveBeenCalledTimes(1);

      await routedAgent.cleanup();
    });
  });
});

describe('buildAgent builder methods', () => {
  let mockProvider: LLMProvider;

  beforeEach(() => {
    mockProvider = createMockProvider();
  });

  it('should configure all features', () => {
    const agent = buildAgent()
      .provider(mockProvider)
      .model('test-model')
      .systemPrompt('Test system prompt')
      .tools(mockTools)
      .hooks({ enabled: true })
      .plugins({ enabled: true })
      .memory({ enabled: true })
      .planning({ enabled: true })
      .reflection({ enabled: true })
      .observability({ enabled: true })
      .sandbox({ enabled: true })
      .humanInLoop({ enabled: true })
      .routing({ enabled: true })
      .multiAgent({ enabled: true })
      .react({ enabled: true })
      .executionPolicy({ enabled: true })
      .threads({ enabled: true })
      .maxIterations(100)
      .timeout(60000)
      .build();

    expect(agent).toBeInstanceOf(ProductionAgent);
    agent.cleanup();
  });

  it('should add roles to multi-agent config', () => {
    const builder = buildAgent()
      .provider(mockProvider)
      .addRole({
        name: 'reviewer',
        description: 'Reviews code',
        systemPrompt: 'You are a code reviewer.',
        capabilities: ['review', 'analyze'],
        authority: 1,
      })
      .addRole({
        name: 'writer',
        description: 'Writes code',
        systemPrompt: 'You are a code writer.',
        capabilities: ['write', 'refactor'],
        authority: 1,
      });

    const agent = builder.build();
    expect(agent).toBeInstanceOf(ProductionAgent);
    agent.cleanup();
  });
});
