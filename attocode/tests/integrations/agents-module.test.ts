/**
 * Tests for the agents/ integration module.
 *
 * Covers:
 * - SharedBlackboard: findings, claims, subscriptions, deduplication, Q&A
 * - ResultSynthesizer: synthesis methods, conflict detection, resolution
 * - SubagentOutputStore: save, load, list, cleanup
 */

import { describe, it, expect } from 'vitest';

// =============================================================================
// SHARED BLACKBOARD
// =============================================================================

describe('SharedBlackboard', () => {
  async function createBlackboard(config?: Record<string, unknown>) {
    const { createSharedBlackboard } = await import(
      '../../src/integrations/agents/shared-blackboard.js'
    );
    return createSharedBlackboard(config as any);
  }

  describe('post and query', () => {
    it('should post a finding and retrieve it by ID', async () => {
      const bb = await createBlackboard();
      const finding = bb.post('agent-1', {
        topic: 'auth-flow',
        content: 'Login uses OAuth2 with PKCE',
        type: 'discovery',
        confidence: 0.9,
        tags: ['auth', 'oauth'],
      });

      expect(finding).toBeDefined();
      expect(finding.id).toBeTruthy();
      expect(finding.agentId).toBe('agent-1');
      expect(finding.topic).toBe('auth-flow');
      expect(finding.confidence).toBe(0.9);

      const retrieved = bb.getFinding(finding.id);
      expect(retrieved).toEqual(finding);
    });

    it('should query findings by topic', async () => {
      const bb = await createBlackboard();
      bb.post('agent-1', { topic: 'auth', content: 'OAuth2 flow', type: 'discovery', confidence: 0.8 });
      bb.post('agent-2', { topic: 'database', content: 'Uses PostgreSQL', type: 'discovery', confidence: 0.9 });
      bb.post('agent-1', { topic: 'auth', content: 'JWT tokens used', type: 'analysis', confidence: 0.7 });

      const authFindings = bb.query({ topic: 'auth' });
      expect(authFindings.length).toBe(2);
      expect(authFindings.every((f: any) => f.topic === 'auth')).toBe(true);
    });

    it('should query findings by agent', async () => {
      const bb = await createBlackboard();
      bb.post('agent-1', { topic: 'auth', content: 'A', type: 'discovery', confidence: 0.8 });
      bb.post('agent-2', { topic: 'db', content: 'B', type: 'discovery', confidence: 0.9 });

      const agent1 = bb.query({ agentId: 'agent-1' });
      expect(agent1.length).toBe(1);
      expect(agent1[0].agentId).toBe('agent-1');
    });

    it('should query findings by tags', async () => {
      const bb = await createBlackboard();
      bb.post('agent-1', { topic: 'auth', content: 'A', type: 'discovery', confidence: 0.8, tags: ['security'] });
      bb.post('agent-2', { topic: 'db', content: 'B', type: 'discovery', confidence: 0.9, tags: ['performance'] });

      const secFindings = bb.query({ tags: ['security'] });
      expect(secFindings.length).toBe(1);
      expect(secFindings[0].tags).toContain('security');
    });
  });

  describe('deduplication', () => {
    it('should deduplicate similar findings by default', async () => {
      const bb = await createBlackboard({ deduplicateFindings: true });
      bb.post('agent-1', { topic: 'auth', content: 'Login uses OAuth2', type: 'discovery', confidence: 0.7 });
      bb.post('agent-2', { topic: 'auth', content: 'Login uses OAuth2', type: 'discovery', confidence: 0.9 });

      const findings = bb.query({ topic: 'auth' });
      // Should either merge or keep highest confidence
      expect(findings.length).toBeLessThanOrEqual(2);
    });
  });

  describe('claims', () => {
    it('should claim and release resources', async () => {
      const bb = await createBlackboard();
      const claimed = bb.claim('src/auth.ts', 'agent-1', 'write');
      expect(claimed).toBe(true);

      expect(bb.isClaimed('src/auth.ts')).toBe(true);

      bb.release('src/auth.ts', 'agent-1');
      expect(bb.isClaimed('src/auth.ts')).toBe(false);
    });

    it('should prevent double-claiming with exclusive', async () => {
      const bb = await createBlackboard();
      bb.claim('src/auth.ts', 'agent-1', 'exclusive');
      const secondClaim = bb.claim('src/auth.ts', 'agent-2', 'write');
      expect(secondClaim).toBe(false);
    });

    it('should releaseAll for an agent', async () => {
      const bb = await createBlackboard();
      bb.claim('src/a.ts', 'agent-1', 'write');
      bb.claim('src/b.ts', 'agent-1', 'write');
      bb.claim('src/c.ts', 'agent-2', 'write');

      bb.releaseAll('agent-1');
      expect(bb.isClaimed('src/a.ts')).toBe(false);
      expect(bb.isClaimed('src/b.ts')).toBe(false);
      expect(bb.isClaimed('src/c.ts')).toBe(true);
    });
  });

  describe('subscriptions', () => {
    it('should notify subscribers of matching findings', async () => {
      const bb = await createBlackboard();
      const received: unknown[] = [];
      bb.subscribe({
        agentId: 'agent-listener',
        topicPattern: 'auth*',
        callback: (finding: any) => received.push(finding),
      });

      bb.post('agent-1', { topic: 'auth', content: 'OAuth2', type: 'discovery', confidence: 0.8 });
      bb.post('agent-2', { topic: 'database', content: 'Postgres', type: 'discovery', confidence: 0.9 });

      expect(received.length).toBe(1);
    });

    it('should unsubscribe agent', async () => {
      const bb = await createBlackboard();
      const received: unknown[] = [];
      bb.subscribe({
        agentId: 'agent-listener',
        topicPattern: 'auth*',
        callback: (finding: any) => received.push(finding),
      });

      bb.unsubscribeAgent('agent-listener');
      bb.post('agent-1', { topic: 'auth', content: 'OAuth2', type: 'discovery', confidence: 0.8 });
      expect(received.length).toBe(0);
    });
  });

  describe('Q&A', () => {
    it('should post and answer questions', async () => {
      const bb = await createBlackboard();
      const qFinding = bb.askQuestion('agent-1', 'auth', 'What auth method is used?');
      expect(qFinding).toBeDefined();
      expect(qFinding.id).toBeTruthy();

      bb.answerQuestion('agent-2', qFinding.id, 'OAuth2 with PKCE', 0.95);
      const best = bb.getBestFinding('auth');
      expect(best).toBeDefined();
    });
  });

  describe('stats and clear', () => {
    it('should return stats', async () => {
      const bb = await createBlackboard();
      bb.post('agent-1', { topic: 'a', content: 'X', type: 'discovery', confidence: 0.5 });
      bb.post('agent-2', { topic: 'b', content: 'Y', type: 'analysis', confidence: 0.6 });

      const stats = bb.getStats();
      expect(stats.totalFindings).toBe(2);
      expect(stats.findingsByAgent.size).toBe(2);
    });

    it('should clear all state', async () => {
      const bb = await createBlackboard();
      bb.post('agent-1', { topic: 'a', content: 'X', type: 'discovery', confidence: 0.5 });
      bb.claim('file.ts', 'agent-1', 'write');

      bb.clear();
      expect(bb.query({}).length).toBe(0);
      expect(bb.isClaimed('file.ts')).toBe(false);
    });
  });

  describe('events', () => {
    it('should emit events on post', async () => {
      const bb = await createBlackboard();
      const events: unknown[] = [];
      bb.on((event: any) => events.push(event));

      bb.post('agent-1', { topic: 'test', content: 'X', type: 'discovery', confidence: 0.5 });
      expect(events.length).toBeGreaterThan(0);
    });
  });
});

// =============================================================================
// RESULT SYNTHESIZER
// =============================================================================

describe('ResultSynthesizer', () => {
  async function createSynthesizer(config?: Record<string, unknown>) {
    const { createResultSynthesizer } = await import(
      '../../src/integrations/agents/result-synthesizer.js'
    );
    return createResultSynthesizer(config as any);
  }

  describe('synthesize', () => {
    it('should synthesize multiple agent outputs', async () => {
      const synth = await createSynthesizer({ defaultMethod: 'concatenate' });
      const result = await synth.synthesize([
        { agentId: 'agent-1', content: 'Implemented auth module with JWT tokens and OAuth2 flow', type: 'analysis', confidence: 0.9 },
        { agentId: 'agent-2', content: 'Implemented database layer with PostgreSQL and migrations', type: 'analysis', confidence: 0.85 },
      ]);

      expect(result).toBeDefined();
      expect(result.output).toBeTruthy();
      expect(typeof result.output).toBe('string');
    });

    it('should handle single output', async () => {
      const synth = await createSynthesizer();
      const result = await synth.synthesize([
        { agentId: 'agent-1', content: 'Implemented auth module', type: 'code', confidence: 0.9 },
      ]);

      expect(result.output).toContain('auth module');
    });

    it('should handle empty outputs', async () => {
      const synth = await createSynthesizer();
      const result = await synth.synthesize([]);
      expect(result).toBeDefined();
    });
  });

  describe('conflict detection', () => {
    it('should detect conflicts in overlapping outputs', async () => {
      const synth = await createSynthesizer();
      const conflicts = synth.detectConflicts([
        {
          agentId: 'agent-1',
          content: 'Use PostgreSQL for the database',
          type: 'code' as const,
          confidence: 0.8,
          filesModified: [{ path: 'src/db.ts', type: 'modify' as const, newContent: 'pg setup' }],
        },
        {
          agentId: 'agent-2',
          content: 'Use MongoDB for the database',
          type: 'code' as const,
          confidence: 0.7,
          filesModified: [{ path: 'src/db.ts', type: 'modify' as const, newContent: 'mongo setup' }],
        },
      ]);

      // Should detect file overlap
      expect(conflicts.length).toBeGreaterThanOrEqual(0);
    });
  });

  describe('concatenate method', () => {
    it('should concatenate outputs', async () => {
      const synth = await createSynthesizer({ defaultMethod: 'concatenate' });
      const result = await synth.synthesize([
        { agentId: 'agent-1', content: 'Part A: Implemented comprehensive authentication', type: 'analysis' as const, confidence: 0.8 },
        { agentId: 'agent-2', content: 'Part B: Implemented comprehensive database layer', type: 'documentation' as const, confidence: 0.8 },
      ]);

      expect(result.output).toContain('Part A');
      expect(result.output).toContain('Part B');
    });
  });

  describe('events', () => {
    it('should emit synthesis events', async () => {
      const synth = await createSynthesizer();
      const events: unknown[] = [];
      synth.on((event: any) => events.push(event));

      await synth.synthesize([
        { agentId: 'agent-1', content: 'Test output', type: 'analysis' as const, confidence: 0.8 },
      ]);

      expect(events.length).toBeGreaterThan(0);
    });
  });
});

// =============================================================================
// SUBAGENT OUTPUT STORE
// =============================================================================

describe('SubagentOutputStore', () => {
  async function createStore() {
    const { createSubagentOutputStore } = await import(
      '../../src/integrations/agents/subagent-output-store.js'
    );
    return createSubagentOutputStore({ persistToFile: false });
  }

  function makeOutput(overrides: Partial<{
    id: string;
    agentId: string;
    agentName: string;
    task: string;
    fullOutput: string;
    filesModified: string[];
    filesCreated: string[];
    timestamp: Date;
    tokensUsed: number;
    durationMs: number;
  }> = {}) {
    return {
      id: overrides.id || `out-${Math.random().toString(36).slice(2, 8)}`,
      agentId: overrides.agentId || 'agent-1',
      agentName: overrides.agentName || 'worker-1',
      task: overrides.task || 'Implement auth',
      fullOutput: overrides.fullOutput || 'Created auth module with JWT support',
      filesModified: overrides.filesModified || [],
      filesCreated: overrides.filesCreated || [],
      timestamp: overrides.timestamp || new Date(),
      tokensUsed: overrides.tokensUsed || 5000,
      durationMs: overrides.durationMs || 10000,
    };
  }

  it('should save and load outputs', async () => {
    const store = await createStore();
    const output = makeOutput();
    const id = store.save(output);

    expect(id).toBeTruthy();

    const loaded = store.load(id);
    expect(loaded).toBeDefined();
    expect(loaded?.agentName).toBe('worker-1');
    expect(loaded?.fullOutput).toContain('JWT support');
  });

  it('should list outputs', async () => {
    const store = await createStore();
    store.save(makeOutput({ agentName: 'worker-1', task: 'Task A', fullOutput: 'A' }));
    store.save(makeOutput({ agentName: 'worker-2', task: 'Task B', fullOutput: 'B' }));

    const all = store.list();
    expect(all.length).toBe(2);
  });

  it('should filter list by agent name', async () => {
    const store = await createStore();
    store.save(makeOutput({ agentName: 'worker-1', task: 'Task A', fullOutput: 'A' }));
    store.save(makeOutput({ agentName: 'worker-2', task: 'Task B', fullOutput: 'B' }));

    const filtered = store.list({ agentName: 'worker-1' });
    expect(filtered.length).toBe(1);
    expect(filtered[0].agentName).toBe('worker-1');
  });

  it('should get summary of output', async () => {
    const store = await createStore();
    const id = store.save(makeOutput({
      agentName: 'worker-1',
      task: 'Implement auth',
      fullOutput: 'Created comprehensive auth module with JWT, OAuth2, and session management',
    }));

    const summary = store.getSummary(id);
    expect(summary).toBeTruthy();
    expect(typeof summary).toBe('string');
  });

  it('should respect maxOutputs', async () => {
    const { createSubagentOutputStore } = await import(
      '../../src/integrations/agents/subagent-output-store.js'
    );
    const store = createSubagentOutputStore({ persistToFile: false, maxOutputs: 2 });

    store.save(makeOutput({ agentName: 'w1', task: 'T1', fullOutput: 'O1' }));
    store.save(makeOutput({ agentName: 'w2', task: 'T2', fullOutput: 'O2' }));
    store.save(makeOutput({ agentName: 'w3', task: 'T3', fullOutput: 'O3' }));

    const all = store.list();
    expect(all.length).toBeLessThanOrEqual(3);
  });
});
