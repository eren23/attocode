/**
 * Recitation Tests
 *
 * Tests for the goal/plan recitation trick that combats "lost in the middle"
 * attention issues in long conversations.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  RecitationManager,
  createRecitationManager,
  buildQuickRecitation,
  calculateOptimalFrequency,
  formatRecitationHistory,
  type RecitationConfig,
  type RecitationState,
  type RecitationMessage,
  type RecitationEvent,
  type RecitationEntry,
  type PlanState,
  type PlanTask,
  type TodoItem,
} from '../../src/tricks/recitation.js';

// =============================================================================
// TEST HELPERS
// =============================================================================

function createTestConfig(overrides: Partial<RecitationConfig> = {}): RecitationConfig {
  return {
    frequency: 5,
    sources: ['goal', 'plan', 'todo'],
    maxTokens: 500,
    trackHistory: true,
    ...overrides,
  };
}

function createTestState(overrides: Partial<RecitationState> = {}): RecitationState {
  return {
    iteration: 1,
    goal: 'Implement user authentication',
    ...overrides,
  };
}

function createTestPlan(overrides: Partial<PlanState> = {}): PlanState {
  return {
    description: 'Authentication implementation plan',
    tasks: [
      { id: '1', description: 'Set up database schema', status: 'completed' },
      { id: '2', description: 'Create user model', status: 'in_progress' },
      { id: '3', description: 'Implement login endpoint', status: 'pending' },
      { id: '4', description: 'Add JWT tokens', status: 'pending' },
    ],
    currentTaskIndex: 1,
    ...overrides,
  };
}

function createTestTodos(): TodoItem[] {
  return [
    { content: 'Write unit tests', status: 'completed' },
    { content: 'Fix password validation', status: 'in_progress' },
    { content: 'Add rate limiting', status: 'pending' },
    { content: 'Update documentation', status: 'pending' },
  ];
}

function createTestMessages(): RecitationMessage[] {
  return [
    { role: 'system', content: 'You are a helpful assistant.' },
    { role: 'user', content: 'Help me implement auth.' },
    { role: 'assistant', content: 'I will help you implement authentication.' },
    { role: 'user', content: 'Start with the database.' },
  ];
}

// =============================================================================
// TESTS
// =============================================================================

describe('RecitationManager', () => {
  let manager: RecitationManager;

  beforeEach(() => {
    manager = createRecitationManager(createTestConfig());
  });

  describe('initialization', () => {
    it('should create manager with provided config', () => {
      const config = createTestConfig({ frequency: 10, maxTokens: 1000 });
      const m = createRecitationManager(config);
      expect(m).toBeInstanceOf(RecitationManager);
    });

    it('should create manager with default optional values', () => {
      const m = createRecitationManager({
        frequency: 5,
        sources: ['goal'],
      });
      expect(m).toBeInstanceOf(RecitationManager);
    });

    it('should initialize with empty history', () => {
      expect(manager.getHistory()).toEqual([]);
    });
  });

  describe('shouldInject', () => {
    it('should return true for first iteration', () => {
      expect(manager.shouldInject(1)).toBe(true);
    });

    it('should return false before frequency is reached', () => {
      // frequency is 5, so iteration 2-5 after initial injection should return false
      manager.injectIfNeeded(createTestMessages(), createTestState({ iteration: 1 }));
      expect(manager.shouldInject(2)).toBe(false);
      expect(manager.shouldInject(3)).toBe(false);
      expect(manager.shouldInject(4)).toBe(false);
      expect(manager.shouldInject(5)).toBe(false);
    });

    it('should return true when frequency is reached', () => {
      manager.injectIfNeeded(createTestMessages(), createTestState({ iteration: 1 }));
      // After iteration 1, should inject at iteration 6 (5 iterations later)
      expect(manager.shouldInject(6)).toBe(true);
    });

    it('should reset counter after injection', () => {
      manager.injectIfNeeded(createTestMessages(), createTestState({ iteration: 1 }));
      manager.injectIfNeeded(createTestMessages(), createTestState({ iteration: 6 }));
      // After injection at 6, should not inject until 11
      expect(manager.shouldInject(7)).toBe(false);
      expect(manager.shouldInject(11)).toBe(true);
    });
  });

  describe('buildRecitation', () => {
    it('should build recitation with goal', () => {
      const content = manager.buildRecitation(createTestState({
        goal: 'Build a REST API',
      }));

      expect(content).toContain('**Goal**: Build a REST API');
    });

    it('should build recitation with plan progress', () => {
      const m = createRecitationManager(createTestConfig({ sources: ['plan'] }));
      const content = m.buildRecitation(createTestState({
        plan: createTestPlan(),
      }));

      expect(content).toContain('**Plan Progress**: 1/4 tasks completed');
      expect(content).toContain('**Current Task**: Create user model');
      expect(content).toContain('**Next**:');
    });

    it('should build recitation with todo summary', () => {
      const m = createRecitationManager(createTestConfig({ sources: ['todo'] }));
      const content = m.buildRecitation(createTestState({
        todos: createTestTodos(),
      }));

      expect(content).toContain('**Todo Status**: 1 done, 1 active, 2 pending');
      expect(content).toContain('**In Progress**: Fix password validation');
      expect(content).toContain('**Remaining**:');
    });

    it('should build recitation with memory context', () => {
      const m = createRecitationManager(createTestConfig({ sources: ['memory'] }));
      const content = m.buildRecitation(createTestState({
        memories: ['User prefers TypeScript', 'Project uses ESM modules'],
      }));

      expect(content).toContain('**Relevant Context**:');
      expect(content).toContain('User prefers TypeScript');
      expect(content).toContain('Project uses ESM modules');
    });

    it('should truncate memories when too many', () => {
      const m = createRecitationManager(createTestConfig({ sources: ['memory'] }));
      const content = m.buildRecitation(createTestState({
        memories: ['Memory 1', 'Memory 2', 'Memory 3', 'Memory 4', 'Memory 5'],
      }));

      expect(content).toContain('(+2 more)');
    });

    it('should include active files if present', () => {
      const content = manager.buildRecitation(createTestState({
        activeFiles: ['src/auth.ts', 'src/user.ts'],
      }));

      expect(content).toContain('**Active files**: src/auth.ts, src/user.ts');
    });

    it('should include recent errors if present', () => {
      const content = manager.buildRecitation(createTestState({
        recentErrors: ['TypeError: undefined is not a function', 'Connection refused'],
      }));

      expect(content).toContain('**Recent errors**:');
      expect(content).toContain('TypeError');
      expect(content).toContain('Connection refused');
    });

    it('should limit recent errors to last 2', () => {
      const content = manager.buildRecitation(createTestState({
        recentErrors: ['Error 1', 'Error 2', 'Error 3'],
      }));

      // Should only show last 2 errors
      expect(content).not.toContain('Error 1');
      expect(content).toContain('Error 2');
      expect(content).toContain('Error 3');
    });

    it('should use custom builder when provided', () => {
      const customBuilder = vi.fn((state: RecitationState) => `Custom: ${state.iteration}`);
      const m = createRecitationManager(createTestConfig({
        sources: ['custom'],
        customBuilder,
      }));

      const content = m.buildRecitation(createTestState({ iteration: 42 }));

      expect(customBuilder).toHaveBeenCalled();
      expect(content).toContain('Custom: 42');
    });

    it('should return null when no content available', () => {
      const m = createRecitationManager(createTestConfig({ sources: ['goal'] }));
      const content = m.buildRecitation(createTestState({ goal: undefined }));

      expect(content).toBeNull();
    });

    it('should truncate content when exceeding maxTokens', () => {
      const m = createRecitationManager(createTestConfig({
        sources: ['goal'],
        maxTokens: 10, // Very small limit
      }));

      const content = m.buildRecitation(createTestState({
        goal: 'This is a very long goal description that should be truncated because it exceeds the token limit',
      }));

      expect(content).toContain('...[truncated]');
    });

    it('should combine multiple sources', () => {
      const content = manager.buildRecitation(createTestState({
        goal: 'Build API',
        plan: createTestPlan(),
        todos: createTestTodos(),
      }));

      expect(content).toContain('**Goal**');
      expect(content).toContain('**Plan Progress**');
      expect(content).toContain('**Todo Status**');
    });
  });

  describe('injectIfNeeded', () => {
    it('should inject recitation at first iteration', () => {
      const messages = createTestMessages();
      const result = manager.injectIfNeeded(messages, createTestState({ iteration: 1 }));

      expect(result.length).toBe(messages.length + 1);
      expect(result.some(m => m.content.includes('[Current Status'))).toBe(true);
    });

    it('should not inject when not due', () => {
      const messages = createTestMessages();
      manager.injectIfNeeded(messages, createTestState({ iteration: 1 }));

      const result = manager.injectIfNeeded(messages, createTestState({ iteration: 2 }));

      expect(result.length).toBe(messages.length);
    });

    it('should insert before last user message', () => {
      const messages = createTestMessages();
      const result = manager.injectIfNeeded(messages, createTestState({ iteration: 1 }));

      // Find the injected message
      const injectedIndex = result.findIndex(m => m.content.includes('[Current Status'));
      const lastUserIndex = result.length - 1; // Last message is user

      expect(injectedIndex).toBe(lastUserIndex - 1);
    });

    it('should append if no user message at end', () => {
      const messages: RecitationMessage[] = [
        { role: 'system', content: 'System message' },
        { role: 'assistant', content: 'Assistant response' },
      ];

      const result = manager.injectIfNeeded(messages, createTestState({ iteration: 1 }));

      // Should append at the end
      expect(result[result.length - 1].content).toContain('[Current Status');
    });

    it('should skip injection when no content to recite', () => {
      const m = createRecitationManager(createTestConfig({ sources: ['goal'] }));
      const messages = createTestMessages();

      const result = m.injectIfNeeded(messages, createTestState({
        iteration: 1,
        goal: undefined,
      }));

      expect(result.length).toBe(messages.length);
    });

    it('should track injection in history', () => {
      manager.injectIfNeeded(createTestMessages(), createTestState({ iteration: 1 }));

      const history = manager.getHistory();
      expect(history.length).toBe(1);
      expect(history[0].iteration).toBe(1);
      expect(history[0].content).toContain('Goal');
    });

    it('should not track history when disabled', () => {
      const m = createRecitationManager(createTestConfig({ trackHistory: false }));
      m.injectIfNeeded(createTestMessages(), createTestState({ iteration: 1 }));

      expect(m.getHistory().length).toBe(0);
    });

    it('should include iteration number in injected message', () => {
      const result = manager.injectIfNeeded(
        createTestMessages(),
        createTestState({ iteration: 15 })
      );

      const injected = result.find(m => m.content.includes('[Current Status'));
      expect(injected?.content).toContain('Iteration 15');
    });
  });

  describe('forceInject', () => {
    it('should inject regardless of frequency', () => {
      const messages = createTestMessages();

      // First normal injection
      manager.injectIfNeeded(messages, createTestState({ iteration: 1 }));

      // Force injection at iteration 2 (should normally be skipped)
      const result = manager.forceInject(messages, createTestState({ iteration: 2 }));

      expect(result.length).toBe(messages.length + 1);
    });

    it('should restore frequency after force inject', () => {
      const messages = createTestMessages();

      manager.forceInject(messages, createTestState({ iteration: 2 }));

      // Should follow normal frequency rules again
      const result = manager.injectIfNeeded(messages, createTestState({ iteration: 3 }));
      expect(result.length).toBe(messages.length); // Not injected
    });
  });

  describe('history management', () => {
    it('should return copy of history', () => {
      manager.injectIfNeeded(createTestMessages(), createTestState({ iteration: 1 }));

      const history1 = manager.getHistory();
      const history2 = manager.getHistory();

      expect(history1).not.toBe(history2);
      expect(history1).toEqual(history2);
    });

    it('should clear history and reset state', () => {
      manager.injectIfNeeded(createTestMessages(), createTestState({ iteration: 1 }));
      manager.clearHistory();

      expect(manager.getHistory().length).toBe(0);
      // Should inject again at iteration 1 after clear
      expect(manager.shouldInject(1)).toBe(true);
    });
  });

  describe('updateConfig', () => {
    it('should update frequency', () => {
      manager.injectIfNeeded(createTestMessages(), createTestState({ iteration: 1 }));

      manager.updateConfig({ frequency: 2 });

      // Should now inject at iteration 3 (2 iterations after 1)
      expect(manager.shouldInject(3)).toBe(true);
    });

    it('should update maxTokens', () => {
      manager.updateConfig({ maxTokens: 10 });

      const content = manager.buildRecitation(createTestState({
        goal: 'A very long goal that exceeds the new token limit',
      }));

      expect(content).toContain('...[truncated]');
    });
  });

  describe('event system', () => {
    it('should emit recitation.injected event', () => {
      const events: RecitationEvent[] = [];
      manager.on(event => events.push(event));

      manager.injectIfNeeded(createTestMessages(), createTestState({ iteration: 1 }));

      expect(events.some(e => e.type === 'recitation.injected')).toBe(true);
      const injected = events.find(e => e.type === 'recitation.injected');
      expect(injected).toMatchObject({
        type: 'recitation.injected',
        iteration: 1,
      });
    });

    it('should emit recitation.skipped event with not_due reason', () => {
      const events: RecitationEvent[] = [];
      manager.on(event => events.push(event));

      manager.injectIfNeeded(createTestMessages(), createTestState({ iteration: 1 }));
      manager.injectIfNeeded(createTestMessages(), createTestState({ iteration: 2 }));

      const skipped = events.find(
        e => e.type === 'recitation.skipped' && (e as any).reason === 'not_due'
      );
      expect(skipped).toBeDefined();
    });

    it('should emit recitation.skipped event with no_content reason', () => {
      const m = createRecitationManager(createTestConfig({ sources: ['goal'] }));
      const events: RecitationEvent[] = [];
      m.on(event => events.push(event));

      m.injectIfNeeded(createTestMessages(), createTestState({
        iteration: 1,
        goal: undefined,
      }));

      const skipped = events.find(
        e => e.type === 'recitation.skipped' && (e as any).reason === 'no_content'
      );
      expect(skipped).toBeDefined();
    });

    it('should emit recitation.built event with token estimate', () => {
      const events: RecitationEvent[] = [];
      manager.on(event => events.push(event));

      manager.buildRecitation(createTestState({ goal: 'Test goal' }));

      const built = events.find(e => e.type === 'recitation.built');
      expect(built).toBeDefined();
      expect((built as any).tokenEstimate).toBeGreaterThan(0);
    });

    it('should allow unsubscribing from events', () => {
      const events: RecitationEvent[] = [];
      const unsubscribe = manager.on(event => events.push(event));

      unsubscribe();

      manager.injectIfNeeded(createTestMessages(), createTestState({ iteration: 1 }));

      expect(events.length).toBe(0);
    });

    it('should handle listener errors gracefully', () => {
      manager.on(() => {
        throw new Error('Listener error');
      });

      // Should not throw
      expect(() => {
        manager.injectIfNeeded(createTestMessages(), createTestState({ iteration: 1 }));
      }).not.toThrow();
    });
  });

  describe('plan summary building', () => {
    it('should show correct progress count', () => {
      const m = createRecitationManager(createTestConfig({ sources: ['plan'] }));
      const plan: PlanState = {
        description: 'Test plan',
        tasks: [
          { id: '1', description: 'Task 1', status: 'completed' },
          { id: '2', description: 'Task 2', status: 'completed' },
          { id: '3', description: 'Task 3', status: 'in_progress' },
          { id: '4', description: 'Task 4', status: 'pending' },
        ],
        currentTaskIndex: 2,
      };

      const content = m.buildRecitation(createTestState({ plan }));

      expect(content).toContain('2/4 tasks completed');
    });

    it('should show current task', () => {
      const m = createRecitationManager(createTestConfig({ sources: ['plan'] }));
      const content = m.buildRecitation(createTestState({ plan: createTestPlan() }));

      expect(content).toContain('**Current Task**: Create user model');
    });

    it('should show up to 2 pending tasks', () => {
      const m = createRecitationManager(createTestConfig({ sources: ['plan'] }));
      const plan: PlanState = {
        description: 'Test plan',
        tasks: [
          { id: '1', description: 'Done task', status: 'completed' },
          { id: '2', description: 'Current task', status: 'in_progress' },
          { id: '3', description: 'Pending 1', status: 'pending' },
          { id: '4', description: 'Pending 2', status: 'pending' },
          { id: '5', description: 'Pending 3', status: 'pending' },
        ],
        currentTaskIndex: 1,
      };

      const content = m.buildRecitation(createTestState({ plan }));

      expect(content).toContain('Pending 1');
      expect(content).toContain('Pending 2');
      expect(content).not.toContain('Pending 3');
    });
  });

  describe('todo summary building', () => {
    it('should show correct status counts', () => {
      const m = createRecitationManager(createTestConfig({ sources: ['todo'] }));
      const content = m.buildRecitation(createTestState({ todos: createTestTodos() }));

      expect(content).toContain('1 done, 1 active, 2 pending');
    });

    it('should show in-progress items', () => {
      const m = createRecitationManager(createTestConfig({ sources: ['todo'] }));
      const content = m.buildRecitation(createTestState({ todos: createTestTodos() }));

      expect(content).toContain('**In Progress**: Fix password validation');
    });

    it('should show all remaining items when 3 or fewer', () => {
      const m = createRecitationManager(createTestConfig({ sources: ['todo'] }));
      const todos: TodoItem[] = [
        { content: 'Task 1', status: 'pending' },
        { content: 'Task 2', status: 'pending' },
        { content: 'Task 3', status: 'pending' },
      ];

      const content = m.buildRecitation(createTestState({ todos }));

      expect(content).toContain('**Remaining**:');
      expect(content).toContain('Task 1');
      expect(content).toContain('Task 2');
      expect(content).toContain('Task 3');
    });

    it('should truncate pending items when more than 3', () => {
      const m = createRecitationManager(createTestConfig({ sources: ['todo'] }));
      const todos: TodoItem[] = [
        { content: 'Task 1', status: 'pending' },
        { content: 'Task 2', status: 'pending' },
        { content: 'Task 3', status: 'pending' },
        { content: 'Task 4', status: 'pending' },
        { content: 'Task 5', status: 'pending' },
      ];

      const content = m.buildRecitation(createTestState({ todos }));

      expect(content).toContain('**Next**:');
      expect(content).toContain('(+2 more)');
    });
  });
});

describe('Factory Functions', () => {
  describe('createRecitationManager', () => {
    it('should create a working manager', () => {
      const manager = createRecitationManager({
        frequency: 5,
        sources: ['goal', 'plan'],
      });

      expect(manager).toBeInstanceOf(RecitationManager);
      expect(manager.shouldInject(1)).toBe(true);
    });
  });
});

describe('Utility Functions', () => {
  describe('buildQuickRecitation', () => {
    it('should build minimal recitation with goal', () => {
      const result = buildQuickRecitation({
        iteration: 1,
        goal: 'Build API',
      });

      expect(result).toBe('Goal: Build API');
    });

    it('should include plan progress', () => {
      const result = buildQuickRecitation({
        iteration: 1,
        goal: 'Build API',
        plan: createTestPlan(),
      });

      expect(result).toContain('Goal: Build API');
      expect(result).toContain('Progress: 1/4 tasks');
      expect(result).toContain('Current: Create user model');
    });

    it('should include todo count', () => {
      const result = buildQuickRecitation({
        iteration: 1,
        todos: createTestTodos(),
      });

      expect(result).toContain('Todos: 3 remaining'); // 1 completed, 3 not
    });

    it('should separate parts with pipe', () => {
      const result = buildQuickRecitation({
        iteration: 1,
        goal: 'Build API',
        todos: createTestTodos(),
      });

      expect(result).toContain(' | ');
    });

    it('should return empty string when no content', () => {
      const result = buildQuickRecitation({ iteration: 1 });
      expect(result).toBe('');
    });
  });

  describe('calculateOptimalFrequency', () => {
    it('should return 10 for light context (<10k tokens)', () => {
      expect(calculateOptimalFrequency(5000)).toBe(10);
      expect(calculateOptimalFrequency(9999)).toBe(10);
    });

    it('should return 7 for medium context (10k-30k tokens)', () => {
      expect(calculateOptimalFrequency(10000)).toBe(7);
      expect(calculateOptimalFrequency(20000)).toBe(7);
      expect(calculateOptimalFrequency(29999)).toBe(7);
    });

    it('should return 5 for heavy context (30k-60k tokens)', () => {
      expect(calculateOptimalFrequency(30000)).toBe(5);
      expect(calculateOptimalFrequency(45000)).toBe(5);
      expect(calculateOptimalFrequency(59999)).toBe(5);
    });

    it('should return 3 for very heavy context (>60k tokens)', () => {
      expect(calculateOptimalFrequency(60000)).toBe(3);
      expect(calculateOptimalFrequency(100000)).toBe(3);
    });
  });

  describe('formatRecitationHistory', () => {
    it('should return message when no history', () => {
      const result = formatRecitationHistory([]);
      expect(result).toBe('No recitation history.');
    });

    it('should format single entry', () => {
      const history: RecitationEntry[] = [
        {
          iteration: 5,
          timestamp: '2024-01-01T12:00:00Z',
          content: 'Goal: Build API',
          sources: ['goal'],
        },
      ];

      const result = formatRecitationHistory(history);

      expect(result).toContain('Recitation History:');
      expect(result).toContain('[Iteration 5]');
      expect(result).toContain('(goal)');
      expect(result).toContain('Goal: Build API');
    });

    it('should show only last 5 entries', () => {
      const history: RecitationEntry[] = Array.from({ length: 10 }, (_, i) => ({
        iteration: i + 1,
        timestamp: '2024-01-01T12:00:00Z',
        content: `Content ${i + 1}`,
        sources: ['goal'] as const,
      }));

      const result = formatRecitationHistory(history);

      // Should only show iterations 6-10
      expect(result).not.toContain('[Iteration 1]');
      expect(result).not.toContain('[Iteration 5]');
      expect(result).toContain('[Iteration 6]');
      expect(result).toContain('[Iteration 10]');
    });

    it('should truncate long content', () => {
      const history: RecitationEntry[] = [
        {
          iteration: 1,
          timestamp: '2024-01-01T12:00:00Z',
          content: 'A'.repeat(150), // More than 100 chars
          sources: ['goal'],
        },
      ];

      const result = formatRecitationHistory(history);

      expect(result).toContain('...');
      expect(result.length).toBeLessThan(history[0].content.length + 100);
    });

    it('should show multiple sources', () => {
      const history: RecitationEntry[] = [
        {
          iteration: 1,
          timestamp: '2024-01-01T12:00:00Z',
          content: 'Goal and plan',
          sources: ['goal', 'plan'],
        },
      ];

      const result = formatRecitationHistory(history);

      expect(result).toContain('(goal, plan)');
    });
  });
});

describe('Edge Cases', () => {
  it('should handle empty plan tasks', () => {
    const manager = createRecitationManager(createTestConfig({ sources: ['plan'] }));
    const plan: PlanState = {
      description: 'Empty plan',
      tasks: [],
      currentTaskIndex: 0,
    };

    const content = manager.buildRecitation(createTestState({ plan }));

    expect(content).toContain('0/0 tasks completed');
  });

  it('should handle plan with no current task', () => {
    const manager = createRecitationManager(createTestConfig({ sources: ['plan'] }));
    const plan: PlanState = {
      description: 'Completed plan',
      tasks: [
        { id: '1', description: 'Task 1', status: 'completed' },
      ],
      currentTaskIndex: 5, // Out of bounds
    };

    const content = manager.buildRecitation(createTestState({ plan }));

    expect(content).toBeDefined();
    expect(content).not.toContain('**Current Task**');
  });

  it('should handle empty todos array', () => {
    const manager = createRecitationManager(createTestConfig({ sources: ['todo'] }));
    const content = manager.buildRecitation(createTestState({ todos: [] }));

    // Empty todos should return null as no content
    expect(content).toBeNull();
  });

  it('should handle empty memories array', () => {
    const manager = createRecitationManager(createTestConfig({ sources: ['memory'] }));
    const content = manager.buildRecitation(createTestState({ memories: [] }));

    expect(content).toBeNull();
  });

  it('should handle custom builder returning null', () => {
    const manager = createRecitationManager(createTestConfig({
      sources: ['custom'],
      customBuilder: () => null,
    }));

    const content = manager.buildRecitation(createTestState({ iteration: 1 }));

    expect(content).toBeNull();
  });

  it('should handle messages with only system message', () => {
    const manager = createRecitationManager(createTestConfig());
    const messages: RecitationMessage[] = [
      { role: 'system', content: 'System only' },
    ];

    const result = manager.injectIfNeeded(messages, createTestState({ iteration: 1 }));

    // Should append at the end since no user message
    expect(result.length).toBe(2);
    expect(result[1].content).toContain('[Current Status');
  });

  it('should handle empty messages array', () => {
    const manager = createRecitationManager(createTestConfig());
    const messages: RecitationMessage[] = [];

    const result = manager.injectIfNeeded(messages, createTestState({ iteration: 1 }));

    expect(result.length).toBe(1);
    expect(result[0].role).toBe('system');
  });

  it('should preserve message types in generic return', () => {
    interface ExtendedMessage extends RecitationMessage {
      customField: string;
    }

    const manager = createRecitationManager(createTestConfig());
    const messages: ExtendedMessage[] = [
      { role: 'user', content: 'Test', customField: 'custom' },
    ];

    const result = manager.injectIfNeeded(messages, createTestState({ iteration: 1 }));

    // Original messages should preserve their type
    const userMsg = result.find(m => m.content === 'Test') as ExtendedMessage | undefined;
    expect(userMsg?.customField).toBe('custom');
  });
});
