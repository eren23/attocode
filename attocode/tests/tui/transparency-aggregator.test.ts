/**
 * Transparency Aggregator Tests
 *
 * Tests for the TUI transparency panel state management.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  TransparencyAggregator,
  createTransparencyAggregator,
  formatTransparencyState,
  getTransparencySummary,
  type TransparencyState,
} from '../../src/tui/transparency-aggregator.js';
import type { AgentEvent } from '../../src/types.js';

describe('TransparencyAggregator', () => {
  let aggregator: TransparencyAggregator;

  beforeEach(() => {
    aggregator = new TransparencyAggregator();
  });

  describe('initialization', () => {
    it('should start with empty state', () => {
      const state = aggregator.getState();

      expect(state.lastRouting).toBeNull();
      expect(state.lastPolicy).toBeNull();
      expect(state.contextHealth).toBeNull();
      expect(state.activeLearnings).toEqual([]);
      expect(state.decisionHistory).toEqual([]);
      expect(state.eventsProcessed).toBe(0);
    });

    it('should accept custom config', () => {
      const customAggregator = new TransparencyAggregator({
        maxHistorySize: 10,
        verbose: true,
      });
      expect(customAggregator.getState().eventsProcessed).toBe(0);
    });
  });

  describe('processEvent', () => {
    it('should track routing decisions', () => {
      const event: AgentEvent = {
        type: 'decision.routing',
        model: 'claude-sonnet-4',
        reason: 'Task requires code analysis',
      };

      aggregator.processEvent(event);
      const state = aggregator.getState();

      expect(state.lastRouting).not.toBeNull();
      expect(state.lastRouting?.model).toBe('claude-sonnet-4');
      expect(state.lastRouting?.reason).toBe('Task requires code analysis');
      expect(state.eventsProcessed).toBe(1);
    });

    it('should track tool decisions', () => {
      const event: AgentEvent = {
        type: 'decision.tool',
        tool: 'write_file',
        decision: 'prompted',
        policyMatch: 'requires-approval',
      };

      aggregator.processEvent(event);
      const state = aggregator.getState();

      expect(state.lastPolicy).not.toBeNull();
      expect(state.lastPolicy?.tool).toBe('write_file');
      expect(state.lastPolicy?.decision).toBe('prompted');
      expect(state.lastPolicy?.reason).toBe('requires-approval');
    });

    it('should track context health', () => {
      const event: AgentEvent = {
        type: 'context.health',
        currentTokens: 50000,
        maxTokens: 200000,
        percentUsed: 25,
        estimatedExchanges: 15,
      };

      aggregator.processEvent(event);
      const state = aggregator.getState();

      expect(state.contextHealth).not.toBeNull();
      expect(state.contextHealth?.currentTokens).toBe(50000);
      expect(state.contextHealth?.maxTokens).toBe(200000);
      expect(state.contextHealth?.percentUsed).toBe(25);
      expect(state.contextHealth?.estimatedExchanges).toBe(15);
    });

    it('should track applied learnings', () => {
      const event: AgentEvent = {
        type: 'learning.applied',
        learningId: 'learn-1',
        context: 'Always check file exists before reading',
      };

      aggregator.processEvent(event);
      const state = aggregator.getState();

      expect(state.activeLearnings).toContain('Always check file exists before reading');
    });

    it('should limit learnings to 5', () => {
      for (let i = 0; i < 7; i++) {
        aggregator.processEvent({
          type: 'learning.applied',
          learningId: `learn-${i}`,
          context: `Learning ${i}`,
        } as AgentEvent);
      }

      const state = aggregator.getState();
      expect(state.activeLearnings).toHaveLength(5);
      expect(state.activeLearnings[0]).toBe('Learning 2'); // First two were shifted out
    });

    it('should not duplicate learnings', () => {
      const event: AgentEvent = {
        type: 'learning.applied',
        learningId: 'learn-dup',
        context: 'Same learning',
      };

      aggregator.processEvent(event);
      aggregator.processEvent(event);

      const state = aggregator.getState();
      expect(state.activeLearnings.filter(l => l === 'Same learning')).toHaveLength(1);
    });

    it('should handle insight.routing events', () => {
      const event: AgentEvent = {
        type: 'insight.routing',
        model: 'claude-haiku',
        reason: 'Quick task',
      };

      aggregator.processEvent(event);
      const state = aggregator.getState();

      expect(state.lastRouting?.model).toBe('claude-haiku');
    });

    it('should handle insight.context events', () => {
      const event: AgentEvent = {
        type: 'insight.context',
        currentTokens: 30000,
        maxTokens: 100000,
        messageCount: 10,
        percentUsed: 30,
      };

      aggregator.processEvent(event);
      const state = aggregator.getState();

      expect(state.contextHealth?.percentUsed).toBe(30);
    });
  });

  describe('decision history', () => {
    it('should add routing decisions to history', () => {
      aggregator.processEvent({
        type: 'decision.routing',
        model: 'claude-sonnet-4',
        reason: 'Complex task',
      } as AgentEvent);

      const state = aggregator.getState();
      expect(state.decisionHistory).toHaveLength(1);
      expect(state.decisionHistory[0].type).toBe('routing');
      expect(state.decisionHistory[0].summary).toContain('claude-sonnet-4');
    });

    it('should add tool decisions to history', () => {
      aggregator.processEvent({
        type: 'decision.tool',
        tool: 'bash',
        decision: 'blocked',
        policyMatch: 'dangerous-command',
      } as AgentEvent);

      const state = aggregator.getState();
      expect(state.decisionHistory).toHaveLength(1);
      expect(state.decisionHistory[0].type).toBe('tool');
      expect(state.decisionHistory[0].summary).toContain('bash');
    });

    it('should respect maxHistorySize', () => {
      const aggregator = new TransparencyAggregator({ maxHistorySize: 3 });

      for (let i = 0; i < 5; i++) {
        aggregator.processEvent({
          type: 'decision.routing',
          model: `model-${i}`,
          reason: `Reason ${i}`,
        } as AgentEvent);
      }

      const state = aggregator.getState();
      expect(state.decisionHistory).toHaveLength(3);
      // Should have models 2, 3, 4 (0 and 1 shifted out)
      expect(state.decisionHistory[0].summary).toContain('model-2');
    });

    it('should add context events to history when verbose', () => {
      const aggregator = new TransparencyAggregator({ verbose: true });

      aggregator.processEvent({
        type: 'context.health',
        currentTokens: 10000,
        maxTokens: 100000,
        percentUsed: 10,
        estimatedExchanges: 20,
      } as AgentEvent);

      const state = aggregator.getState();
      expect(state.decisionHistory.some(d => d.type === 'context')).toBe(true);
    });

    it('should add context events to history when percentUsed >= 70', () => {
      aggregator.processEvent({
        type: 'context.health',
        currentTokens: 75000,
        maxTokens: 100000,
        percentUsed: 75,
        estimatedExchanges: 5,
      } as AgentEvent);

      const state = aggregator.getState();
      expect(state.decisionHistory.some(d => d.type === 'context')).toBe(true);
    });
  });

  describe('reset', () => {
    it('should reset all state', () => {
      aggregator.processEvent({
        type: 'decision.routing',
        model: 'test',
        reason: 'test',
      } as AgentEvent);

      aggregator.reset();
      const state = aggregator.getState();

      expect(state.lastRouting).toBeNull();
      expect(state.eventsProcessed).toBe(0);
      expect(state.decisionHistory).toEqual([]);
    });
  });

  describe('subscribe', () => {
    it('should notify listeners on state changes', () => {
      const listener = vi.fn();
      aggregator.subscribe(listener);

      aggregator.processEvent({
        type: 'decision.routing',
        model: 'test',
        reason: 'test',
      } as AgentEvent);

      expect(listener).toHaveBeenCalled();
      expect(listener.mock.calls[0][0].lastRouting?.model).toBe('test');
    });

    it('should allow unsubscribing', () => {
      const listener = vi.fn();
      const unsubscribe = aggregator.subscribe(listener);

      unsubscribe();

      aggregator.processEvent({
        type: 'decision.routing',
        model: 'test',
        reason: 'test',
      } as AgentEvent);

      expect(listener).not.toHaveBeenCalled();
    });

    it('should handle listener errors gracefully', () => {
      const badListener = vi.fn().mockImplementation(() => {
        throw new Error('Listener error');
      });
      const goodListener = vi.fn();

      aggregator.subscribe(badListener);
      aggregator.subscribe(goodListener);

      // Should not throw
      aggregator.processEvent({
        type: 'decision.routing',
        model: 'test',
        reason: 'test',
      } as AgentEvent);

      expect(goodListener).toHaveBeenCalled();
    });
  });
});

describe('createTransparencyAggregator', () => {
  it('should create a new aggregator', () => {
    const aggregator = createTransparencyAggregator();
    expect(aggregator).toBeInstanceOf(TransparencyAggregator);
  });

  it('should pass config to aggregator', () => {
    const aggregator = createTransparencyAggregator({ maxHistorySize: 5 });
    // Verify by adding more than 5 entries
    for (let i = 0; i < 7; i++) {
      aggregator.processEvent({
        type: 'decision.routing',
        model: `model-${i}`,
        reason: `Reason ${i}`,
      } as AgentEvent);
    }
    expect(aggregator.getState().decisionHistory).toHaveLength(5);
  });
});

describe('formatTransparencyState', () => {
  it('should format empty state', () => {
    const state: TransparencyState = {
      lastRouting: null,
      lastPolicy: null,
      contextHealth: null,
      activeLearnings: [],
      decisionHistory: [],
      eventsProcessed: 0,
    };

    const result = formatTransparencyState(state);
    expect(result).toContain('REASONING');
    expect(result).toContain('no routing decisions yet');
    expect(result).toContain('CONTEXT');
    expect(result).toContain('no context data yet');
  });

  it('should format routing info', () => {
    const state: TransparencyState = {
      lastRouting: {
        model: 'claude-sonnet-4',
        reason: 'Complex code analysis',
        timestamp: Date.now(),
      },
      lastPolicy: null,
      contextHealth: null,
      activeLearnings: [],
      decisionHistory: [],
      eventsProcessed: 1,
    };

    const result = formatTransparencyState(state);
    expect(result).toContain('claude-sonnet-4');
    expect(result).toContain('Complex code analysis');
  });

  it('should format policy decisions with icons', () => {
    const state: TransparencyState = {
      lastRouting: null,
      lastPolicy: {
        tool: 'write_file',
        decision: 'allowed',
        reason: 'safe-pattern',
        timestamp: Date.now(),
      },
      contextHealth: null,
      activeLearnings: [],
      decisionHistory: [],
      eventsProcessed: 1,
    };

    const result = formatTransparencyState(state);
    expect(result).toContain('+ write_file');
    expect(result).toContain('allowed');
  });

  it('should format context health with progress bar', () => {
    const state: TransparencyState = {
      lastRouting: null,
      lastPolicy: null,
      contextHealth: {
        currentTokens: 50000,
        maxTokens: 100000,
        percentUsed: 50,
        estimatedExchanges: 10,
        lastUpdate: Date.now(),
      },
      activeLearnings: [],
      decisionHistory: [],
      eventsProcessed: 1,
    };

    const result = formatTransparencyState(state);
    expect(result).toContain('50%');
    expect(result).toContain('50.0k / 100k tokens');
    expect(result).toContain('10 exchanges remaining');
  });

  it('should format learnings section', () => {
    const state: TransparencyState = {
      lastRouting: null,
      lastPolicy: null,
      contextHealth: null,
      activeLearnings: ['Learning 1', 'Learning 2'],
      decisionHistory: [],
      eventsProcessed: 2,
    };

    const result = formatTransparencyState(state);
    expect(result).toContain('MEMORY');
    expect(result).toContain('Learnings applied: 2');
  });
});

describe('getTransparencySummary', () => {
  it('should return empty string for empty state', () => {
    const state: TransparencyState = {
      lastRouting: null,
      lastPolicy: null,
      contextHealth: null,
      activeLearnings: [],
      decisionHistory: [],
      eventsProcessed: 0,
    };

    const result = getTransparencySummary(state);
    expect(result).toBe('');
  });

  it('should include model suffix', () => {
    const state: TransparencyState = {
      lastRouting: {
        model: 'anthropic-claude-sonnet-4',
        reason: 'test',
        timestamp: Date.now(),
      },
      lastPolicy: null,
      contextHealth: null,
      activeLearnings: [],
      decisionHistory: [],
      eventsProcessed: 1,
    };

    const result = getTransparencySummary(state);
    expect(result).toContain('model:4'); // Last part after split('-')
  });

  it('should include context percentage', () => {
    const state: TransparencyState = {
      lastRouting: null,
      lastPolicy: null,
      contextHealth: {
        currentTokens: 50000,
        maxTokens: 100000,
        percentUsed: 50,
        estimatedExchanges: 10,
        lastUpdate: Date.now(),
      },
      activeLearnings: [],
      decisionHistory: [],
      eventsProcessed: 1,
    };

    const result = getTransparencySummary(state);
    expect(result).toContain('ctx:50%');
  });

  it('should include learning count', () => {
    const state: TransparencyState = {
      lastRouting: null,
      lastPolicy: null,
      contextHealth: null,
      activeLearnings: ['a', 'b', 'c'],
      decisionHistory: [],
      eventsProcessed: 3,
    };

    const result = getTransparencySummary(state);
    expect(result).toContain('L:3');
  });

  it('should join parts with pipe separator', () => {
    const state: TransparencyState = {
      lastRouting: {
        model: 'claude-sonnet',
        reason: 'test',
        timestamp: Date.now(),
      },
      lastPolicy: null,
      contextHealth: {
        currentTokens: 25000,
        maxTokens: 100000,
        percentUsed: 25,
        estimatedExchanges: 15,
        lastUpdate: Date.now(),
      },
      activeLearnings: [],
      decisionHistory: [],
      eventsProcessed: 2,
    };

    const result = getTransparencySummary(state);
    expect(result).toContain(' | ');
  });
});
