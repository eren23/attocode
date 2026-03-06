/**
 * Event System Tests
 *
 * Tests for the agent event emission and handling system.
 * Verifies correct event ordering, listener management, and event payloads.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { EventEmitter } from 'events';
import type { AgentEvent, AgentEventListener, AgentResult, AgentPlan, AgentMetrics } from '../src/types.js';

// Mock metrics for tests
const mockMetrics: AgentMetrics = {
  totalTokens: 100,
  inputTokens: 80,
  outputTokens: 20,
  estimatedCost: 0.01,
  llmCalls: 1,
  toolCalls: 0,
  duration: 1000,
};

// Mock data for tests
const mockPlan: AgentPlan = {
  goal: 'Test goal',
  tasks: [],
  currentTaskIndex: 0,
};

const mockResult: AgentResult = {
  success: true,
  response: 'Test output',
  metrics: mockMetrics,
  messages: [],
};

const mockErrorResult: AgentResult = {
  success: false,
  response: '',
  error: 'Maximum iterations exceeded',
  metrics: mockMetrics,
  messages: [],
};

// =============================================================================
// EVENT EMITTER TESTS
// =============================================================================

describe('Event Emission', () => {
  let emitter: EventEmitter;
  let receivedEvents: AgentEvent[];

  beforeEach(() => {
    emitter = new EventEmitter();
    receivedEvents = [];
    emitter.on('agent-event', (event: AgentEvent) => {
      receivedEvents.push(event);
    });
  });

  describe('basic emission', () => {
    it('should emit events to listeners', () => {
      const event: AgentEvent = {
        type: 'start',
        task: 'Test task',
        traceId: 'trace-123',
      };

      emitter.emit('agent-event', event);

      expect(receivedEvents.length).toBe(1);
      expect(receivedEvents[0].type).toBe('start');
    });

    it('should support multiple listeners', () => {
      const listener1Events: AgentEvent[] = [];
      const listener2Events: AgentEvent[] = [];

      emitter.on('agent-event', (e: AgentEvent) => listener1Events.push(e));
      emitter.on('agent-event', (e: AgentEvent) => listener2Events.push(e));

      const event: AgentEvent = { type: 'start', task: 'Test', traceId: 'trace-1' };
      emitter.emit('agent-event', event);

      // Original listener + 2 new ones = 3 total
      expect(receivedEvents.length).toBe(1);
      expect(listener1Events.length).toBe(1);
      expect(listener2Events.length).toBe(1);
    });

    it('should preserve event order', () => {
      const events: AgentEvent[] = [
        { type: 'start', task: 'Task', traceId: 'trace-1' },
        { type: 'planning', plan: mockPlan },
        { type: 'complete', result: mockResult },
      ];

      for (const event of events) {
        emitter.emit('agent-event', event);
      }

      expect(receivedEvents.length).toBe(3);
      expect(receivedEvents[0].type).toBe('start');
      expect(receivedEvents[1].type).toBe('planning');
      expect(receivedEvents[2].type).toBe('complete');
    });
  });

  describe('listener management', () => {
    it('should allow removing listeners', () => {
      const listener = vi.fn();
      emitter.on('agent-event', listener);

      emitter.emit('agent-event', { type: 'start', task: 'Test', traceId: 'trace-1' });
      expect(listener).toHaveBeenCalledTimes(1);

      emitter.off('agent-event', listener);

      emitter.emit('agent-event', { type: 'start', task: 'Test', traceId: 'trace-2' });
      expect(listener).toHaveBeenCalledTimes(1); // Still 1, not called again
    });

    it('should support once listeners', () => {
      const listener = vi.fn();
      emitter.once('agent-event', listener);

      emitter.emit('agent-event', { type: 'start', task: 'Test', traceId: 'trace-1' });
      emitter.emit('agent-event', { type: 'start', task: 'Test', traceId: 'trace-2' });

      expect(listener).toHaveBeenCalledTimes(1);
    });

    it('should handle listener errors gracefully', () => {
      const errorListener = vi.fn(() => {
        throw new Error('Listener error');
      });
      const normalListener = vi.fn();

      emitter.on('agent-event', errorListener);
      emitter.on('agent-event', normalListener);

      // Node's EventEmitter will throw by default
      expect(() => {
        emitter.emit('agent-event', { type: 'start', task: 'Test', traceId: 'trace-1' });
      }).toThrow('Listener error');
    });
  });
});

// =============================================================================
// EVENT TYPE TESTS
// =============================================================================

describe('Event Types', () => {
  describe('start event', () => {
    it('should have required fields', () => {
      const event: AgentEvent = {
        type: 'start',
        task: 'Implement feature X',
        traceId: 'trace-abc123',
      };

      expect(event.type).toBe('start');
      if (event.type === 'start') {
        expect(event.task).toBeDefined();
        expect(event.traceId).toBeDefined();
      }
    });
  });

  describe('planning event', () => {
    it('should have plan field', () => {
      const event: AgentEvent = {
        type: 'planning',
        plan: mockPlan,
      };

      expect(event.type).toBe('planning');
      if (event.type === 'planning') {
        expect(event.plan).toBeDefined();
        expect(event.plan.goal).toBe('Test goal');
      }
    });
  });

  describe('llm.start event', () => {
    it('should include model', () => {
      const event: AgentEvent = {
        type: 'llm.start',
        model: 'claude-3-opus',
      };

      expect(event.type).toBe('llm.start');
      if (event.type === 'llm.start') {
        expect(event.model).toBe('claude-3-opus');
      }
    });

    it('should optionally include subagent', () => {
      const event: AgentEvent = {
        type: 'llm.start',
        model: 'claude-3-sonnet',
        subagent: 'researcher-1',
      };

      if (event.type === 'llm.start') {
        expect(event.subagent).toBe('researcher-1');
      }
    });
  });

  describe('llm.complete event', () => {
    it('should include response', () => {
      const event: AgentEvent = {
        type: 'llm.complete',
        response: {
          content: 'Response content',
          usage: { inputTokens: 100, outputTokens: 50, totalTokens: 150 },
        },
      };

      expect(event.type).toBe('llm.complete');
      if (event.type === 'llm.complete') {
        expect(event.response.content).toBeDefined();
      }
    });
  });

  describe('tool.start event', () => {
    it('should include tool name and args', () => {
      const event: AgentEvent = {
        type: 'tool.start',
        tool: 'read_file',
        args: { path: '/src/main.ts' },
      };

      expect(event.type).toBe('tool.start');
      if (event.type === 'tool.start') {
        expect(event.tool).toBe('read_file');
        expect(event.args).toEqual({ path: '/src/main.ts' });
      }
    });
  });

  describe('tool.complete event', () => {
    it('should include result', () => {
      const event: AgentEvent = {
        type: 'tool.complete',
        tool: 'read_file',
        result: 'file contents...',
      };

      expect(event.type).toBe('tool.complete');
      if (event.type === 'tool.complete') {
        expect(event.result).toBeDefined();
      }
    });
  });

  describe('approval events', () => {
    it('should handle approval.required', () => {
      const event: AgentEvent = {
        type: 'approval.required',
        request: {
          id: 'req-1',
          action: 'bash',
          tool: 'bash',
          args: { command: 'rm -rf /tmp/test' },
          risk: 'high',
          context: 'destructive command',
        },
      };

      expect(event.type).toBe('approval.required');
      if (event.type === 'approval.required') {
        expect(event.request.tool).toBe('bash');
        expect(event.request.risk).toBe('high');
      }
    });

    it('should handle approval.received', () => {
      const event: AgentEvent = {
        type: 'approval.received',
        response: {
          approved: true,
          reason: 'User approved',
        },
      };

      expect(event.type).toBe('approval.received');
      if (event.type === 'approval.received') {
        expect(event.response.approved).toBe(true);
      }
    });
  });

  describe('complete event', () => {
    it('should include result', () => {
      const event: AgentEvent = {
        type: 'complete',
        result: mockResult,
      };

      expect(event.type).toBe('complete');
      if (event.type === 'complete') {
        expect(event.result.success).toBe(true);
      }
    });

    it('should handle error result', () => {
      const event: AgentEvent = {
        type: 'complete',
        result: mockErrorResult,
      };

      if (event.type === 'complete') {
        expect(event.result.success).toBe(false);
        expect(event.result.error).toBeDefined();
      }
    });
  });

  describe('insight events', () => {
    it('should track token usage', () => {
      const event: AgentEvent = {
        type: 'insight.tokens',
        inputTokens: 1000,
        outputTokens: 500,
        cacheReadTokens: 200,
        cost: 0.05,
        model: 'claude-3-opus',
      };

      expect(event.type).toBe('insight.tokens');
      if (event.type === 'insight.tokens') {
        expect(event.inputTokens).toBe(1000);
        expect(event.outputTokens).toBe(500);
      }
    });

    it('should track context health', () => {
      const event: AgentEvent = {
        type: 'insight.context',
        currentTokens: 50000,
        maxTokens: 200000,
        messageCount: 25,
        percentUsed: 25,
      };

      expect(event.type).toBe('insight.context');
      if (event.type === 'insight.context') {
        expect(event.percentUsed).toBe(25);
      }
    });
  });

  describe('mode events', () => {
    it('should track mode changes', () => {
      const event: AgentEvent = {
        type: 'mode.changed',
        from: 'build',
        to: 'plan',
      };

      expect(event.type).toBe('mode.changed');
      if (event.type === 'mode.changed') {
        expect(event.from).toBe('build');
        expect(event.to).toBe('plan');
      }
    });
  });

  describe('plan mode events', () => {
    it('should track queued changes', () => {
      const event: AgentEvent = {
        type: 'plan.change.queued',
        tool: 'write_file',
        changeId: 'change-1',
        summary: 'Add new feature',
      };

      expect(event.type).toBe('plan.change.queued');
      if (event.type === 'plan.change.queued') {
        expect(event.tool).toBe('write_file');
      }
    });

    it('should track plan approval', () => {
      const event: AgentEvent = {
        type: 'plan.approved',
        changeCount: 5,
      };

      expect(event.type).toBe('plan.approved');
      if (event.type === 'plan.approved') {
        expect(event.changeCount).toBe(5);
      }
    });
  });

  describe('subagent events', () => {
    it('should track subagent spawn', () => {
      const event: AgentEvent = {
        type: 'agent.spawn',
        agentId: 'agent-123',
        name: 'researcher',
        task: 'Explore codebase',
      };

      expect(event.type).toBe('agent.spawn');
      if (event.type === 'agent.spawn') {
        expect(event.name).toBe('researcher');
      }
    });

    it('should track subagent completion', () => {
      const event: AgentEvent = {
        type: 'agent.complete',
        agentId: 'agent-123',
        success: true,
        output: 'Found 5 relevant files',
      };

      expect(event.type).toBe('agent.complete');
      if (event.type === 'agent.complete') {
        expect(event.success).toBe(true);
      }
    });

    it('should track subagent iteration', () => {
      const event: AgentEvent = {
        type: 'subagent.iteration',
        agentId: 'agent-123',
        iteration: 5,
        maxIterations: 30,
      };

      expect(event.type).toBe('subagent.iteration');
      if (event.type === 'subagent.iteration') {
        expect(event.iteration).toBe(5);
      }
    });
  });
});

// =============================================================================
// EVENT ORDERING TESTS
// =============================================================================

describe('Event Ordering', () => {
  it('should emit events in correct lifecycle order', () => {
    const events: AgentEvent['type'][] = [];
    const emitter = new EventEmitter();

    emitter.on('agent-event', (e: AgentEvent) => events.push(e.type));

    // Simulate agent lifecycle
    emitter.emit('agent-event', { type: 'start', task: 'Test', traceId: 'trace-1' } satisfies AgentEvent);
    emitter.emit('agent-event', { type: 'planning', plan: mockPlan } satisfies AgentEvent);
    emitter.emit('agent-event', { type: 'llm.start', model: 'claude' } satisfies AgentEvent);
    emitter.emit('agent-event', { type: 'llm.complete', response: { content: '', usage: { inputTokens: 0, outputTokens: 0, totalTokens: 0 } } } satisfies AgentEvent);
    emitter.emit('agent-event', { type: 'tool.start', tool: 'read_file', args: {} } satisfies AgentEvent);
    emitter.emit('agent-event', { type: 'tool.complete', tool: 'read_file', result: '' } satisfies AgentEvent);
    emitter.emit('agent-event', { type: 'complete', result: mockResult } satisfies AgentEvent);

    expect(events).toEqual([
      'start',
      'planning',
      'llm.start',
      'llm.complete',
      'tool.start',
      'tool.complete',
      'complete',
    ]);
  });

  it('should handle nested tool calls correctly', () => {
    const events: string[] = [];
    const emitter = new EventEmitter();

    emitter.on('agent-event', (e: AgentEvent) => {
      if (e.type === 'tool.start' || e.type === 'tool.complete') {
        events.push(`${e.type}:${e.tool}`);
      }
    });

    // Simulate nested tool calls
    emitter.emit('agent-event', { type: 'tool.start', tool: 'bash', args: {} } satisfies AgentEvent);
    emitter.emit('agent-event', { type: 'tool.start', tool: 'read_file', args: {} } satisfies AgentEvent);
    emitter.emit('agent-event', { type: 'tool.complete', tool: 'read_file', result: '' } satisfies AgentEvent);
    emitter.emit('agent-event', { type: 'tool.complete', tool: 'bash', result: '' } satisfies AgentEvent);

    expect(events).toEqual([
      'tool.start:bash',
      'tool.start:read_file',
      'tool.complete:read_file',
      'tool.complete:bash',
    ]);
  });
});

// =============================================================================
// EVENT FILTERING TESTS
// =============================================================================

describe('Event Filtering', () => {
  it('should filter events by type', () => {
    const emitter = new EventEmitter();
    const toolEvents: AgentEvent[] = [];

    emitter.on('agent-event', (e: AgentEvent) => {
      if (e.type.startsWith('tool.')) {
        toolEvents.push(e);
      }
    });

    emitter.emit('agent-event', { type: 'start', task: 'Test', traceId: 'trace-1' } satisfies AgentEvent);
    emitter.emit('agent-event', { type: 'tool.start', tool: 'read_file', args: {} } satisfies AgentEvent);
    emitter.emit('agent-event', { type: 'llm.start', model: 'claude' } satisfies AgentEvent);
    emitter.emit('agent-event', { type: 'tool.complete', tool: 'read_file', result: '' } satisfies AgentEvent);
    emitter.emit('agent-event', { type: 'complete', result: mockResult } satisfies AgentEvent);

    expect(toolEvents.length).toBe(2);
    expect(toolEvents.every(e => e.type.startsWith('tool.'))).toBe(true);
  });

  it('should aggregate token counts from insight events', () => {
    const emitter = new EventEmitter();
    let totalInputTokens = 0;
    let totalOutputTokens = 0;

    emitter.on('agent-event', (e: AgentEvent) => {
      if (e.type === 'insight.tokens') {
        totalInputTokens += e.inputTokens;
        totalOutputTokens += e.outputTokens;
      }
    });

    emitter.emit('agent-event', { type: 'insight.tokens', inputTokens: 1000, outputTokens: 500, model: 'claude' } satisfies AgentEvent);
    emitter.emit('agent-event', { type: 'insight.tokens', inputTokens: 1500, outputTokens: 800, model: 'claude' } satisfies AgentEvent);
    emitter.emit('agent-event', { type: 'insight.tokens', inputTokens: 2000, outputTokens: 1000, model: 'claude' } satisfies AgentEvent);

    expect(totalInputTokens).toBe(4500);
    expect(totalOutputTokens).toBe(2300);
  });
});

// =============================================================================
// AGENT EVENT LISTENER TYPE TESTS
// =============================================================================

describe('AgentEventListener', () => {
  it('should accept events', () => {
    const listener: AgentEventListener = (event) => {
      expect(event.type).toBeDefined();
    };

    const event: AgentEvent = { type: 'start', task: 'Test', traceId: 'trace-1' };
    listener(event);
  });

  it('should handle all event types', () => {
    const seenTypes = new Set<string>();
    const listener: AgentEventListener = (event) => {
      seenTypes.add(event.type);
    };

    // Emit various event types
    listener({ type: 'start', task: 'Test', traceId: 'trace-1' });
    listener({ type: 'planning', plan: mockPlan });
    listener({ type: 'tool.start', tool: 'test', args: {} });
    listener({ type: 'complete', result: mockResult });

    expect(seenTypes.size).toBe(4);
  });
});
