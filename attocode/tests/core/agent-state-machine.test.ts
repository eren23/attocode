/**
 * Agent State Machine Tests (Phase 2.2)
 *
 * Tests for phase transitions, event emission, metric tracking,
 * saturation detection, and auto-transitions.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  AgentStateMachine,
  createAgentStateMachine,
  type AgentPhase,
  type StateMachineEvent,
} from '../../src/core/agent-state-machine.js';

// =============================================================================
// FACTORY
// =============================================================================

describe('createAgentStateMachine', () => {
  it('creates a state machine with default exploring phase', () => {
    const sm = createAgentStateMachine();
    expect(sm.getPhase()).toBe('exploring');
  });

  it('accepts custom initial phase', () => {
    const sm = createAgentStateMachine({ initialPhase: 'acting' });
    expect(sm.getPhase()).toBe('acting');
  });
});

// =============================================================================
// PHASE TRANSITIONS
// =============================================================================

describe('Phase Transitions', () => {
  let sm: AgentStateMachine;

  beforeEach(() => {
    sm = createAgentStateMachine();
  });

  it('exploring → acting is valid', () => {
    expect(sm.transition('acting', 'First edit')).toBe(true);
    expect(sm.getPhase()).toBe('acting');
  });

  it('exploring → planning is valid', () => {
    expect(sm.transition('planning', 'Creating plan')).toBe(true);
    expect(sm.getPhase()).toBe('planning');
  });

  it('exploring → verifying is invalid', () => {
    expect(sm.transition('verifying', 'Premature test')).toBe(false);
    expect(sm.getPhase()).toBe('exploring');
  });

  it('acting → verifying is valid', () => {
    sm.transition('acting', 'Edit');
    expect(sm.transition('verifying', 'Running tests')).toBe(true);
    expect(sm.getPhase()).toBe('verifying');
  });

  it('acting → exploring is valid (backtrack)', () => {
    sm.transition('acting', 'Edit');
    expect(sm.transition('exploring', 'Need more context')).toBe(true);
    expect(sm.getPhase()).toBe('exploring');
  });

  it('verifying → acting is valid (fix loop)', () => {
    sm.transition('acting', 'Edit');
    sm.transition('verifying', 'Test');
    expect(sm.transition('acting', 'Fix failure')).toBe(true);
    expect(sm.getPhase()).toBe('acting');
  });

  it('planning → acting is valid', () => {
    sm.transition('planning', 'Plan');
    expect(sm.transition('acting', 'Execute plan')).toBe(true);
    expect(sm.getPhase()).toBe('acting');
  });

  it('planning → exploring is valid (need more info)', () => {
    sm.transition('planning', 'Plan');
    expect(sm.transition('exploring', 'Need info')).toBe(true);
    expect(sm.getPhase()).toBe('exploring');
  });

  it('same phase transition returns false', () => {
    expect(sm.transition('exploring', 'Already here')).toBe(false);
  });

  it('planning → verifying is invalid', () => {
    sm.transition('planning', 'Plan');
    expect(sm.transition('verifying', 'Skip acting')).toBe(false);
    expect(sm.getPhase()).toBe('planning');
  });

  it('verifying → planning is invalid', () => {
    sm.transition('acting', 'Edit');
    sm.transition('verifying', 'Test');
    expect(sm.transition('planning', 'Replan')).toBe(false);
    expect(sm.getPhase()).toBe('verifying');
  });
});

// =============================================================================
// EVENT EMISSION
// =============================================================================

describe('Event Emission', () => {
  let sm: AgentStateMachine;
  let events: StateMachineEvent[];

  beforeEach(() => {
    sm = createAgentStateMachine();
    events = [];
    sm.subscribe(e => events.push(e));
  });

  it('emits phase.changed on valid transition', () => {
    sm.transition('acting', 'First edit');
    expect(events).toHaveLength(1);
    expect(events[0].type).toBe('phase.changed');
    if (events[0].type === 'phase.changed') {
      expect(events[0].transition.from).toBe('exploring');
      expect(events[0].transition.to).toBe('acting');
      expect(events[0].transition.reason).toBe('First edit');
    }
  });

  it('does not emit on invalid transition', () => {
    sm.transition('verifying', 'Invalid');
    expect(events).toHaveLength(0);
  });

  it('does not emit on same-phase transition', () => {
    sm.transition('exploring', 'Same');
    expect(events).toHaveLength(0);
  });

  it('unsubscribe prevents further events', () => {
    const unsub = sm.subscribe(e => events.push(e));
    unsub();
    // Clear events from initial subscribe
    events.length = 0;
    sm.transition('acting', 'Test');
    // Only the first subscriber should have caught it
    expect(events).toHaveLength(1); // From the beforeEach subscriber
  });

  it('listener errors do not break the state machine', () => {
    sm.subscribe(() => { throw new Error('bad listener'); });
    expect(() => sm.transition('acting', 'Test')).not.toThrow();
    expect(sm.getPhase()).toBe('acting');
  });
});

// =============================================================================
// PHASE METRICS
// =============================================================================

describe('Phase Metrics', () => {
  let sm: AgentStateMachine;

  beforeEach(() => {
    sm = createAgentStateMachine();
  });

  it('tracks iterations in current phase', () => {
    sm.recordToolCall('read_file', { path: '/a.ts' });
    sm.recordToolCall('read_file', { path: '/b.ts' });
    const metrics = sm.getCurrentPhaseMetrics();
    expect(metrics.iterations).toBe(2);
    expect(metrics.filesRead).toBe(2);
    expect(metrics.phase).toBe('exploring');
  });

  it('resets counters on phase transition', () => {
    sm.recordToolCall('read_file', { path: '/a.ts' });
    sm.recordToolCall('read_file', { path: '/b.ts' });
    sm.transition('acting', 'Edit');
    const metrics = sm.getCurrentPhaseMetrics();
    expect(metrics.iterations).toBe(0);
    expect(metrics.phase).toBe('acting');
  });

  it('records phase history on transition', () => {
    sm.recordToolCall('read_file', { path: '/a.ts' });
    sm.transition('acting', 'Edit');
    const history = sm.getPhaseHistory();
    expect(history).toHaveLength(1);
    expect(history[0].phase).toBe('exploring');
    expect(history[0].iterations).toBe(1);
    expect(history[0].filesRead).toBe(1);
  });

  it('tracks file modifications', () => {
    sm.transition('acting', 'Start editing');
    sm.recordToolCall('write_file', { path: '/a.ts', content: 'test' });
    sm.recordToolCall('edit_file', { path: '/b.ts', old: 'x', new: 'y' });
    const metrics = sm.getCurrentPhaseMetrics();
    expect(metrics.filesModified).toBe(2);
  });

  it('tracks tool calls per phase', () => {
    sm.recordToolCall('grep', { pattern: 'foo' });
    sm.recordToolCall('read_file', { path: '/a.ts' });
    const metrics = sm.getCurrentPhaseMetrics();
    expect(metrics.toolCalls).toBe(2);
  });
});

// =============================================================================
// TRANSITION HISTORY
// =============================================================================

describe('Transition History', () => {
  it('records all transitions', () => {
    const sm = createAgentStateMachine();
    sm.transition('acting', 'Edit');
    sm.transition('verifying', 'Test');
    sm.transition('acting', 'Fix');

    const transitions = sm.getTransitions();
    expect(transitions).toHaveLength(3);
    expect(transitions[0].from).toBe('exploring');
    expect(transitions[0].to).toBe('acting');
    expect(transitions[1].from).toBe('acting');
    expect(transitions[1].to).toBe('verifying');
    expect(transitions[2].from).toBe('verifying');
    expect(transitions[2].to).toBe('acting');
  });

  it('includes fromMetrics in transitions', () => {
    const sm = createAgentStateMachine();
    sm.recordToolCall('read_file', { path: '/a.ts' });
    sm.recordToolCall('read_file', { path: '/b.ts' });
    sm.transition('acting', 'Edit');

    const transitions = sm.getTransitions();
    expect(transitions[0].fromMetrics.iterations).toBe(2);
    expect(transitions[0].fromMetrics.filesRead).toBe(2);
  });
});

// =============================================================================
// AUTO-TRANSITIONS
// =============================================================================

describe('Auto-Transitions', () => {
  let sm: AgentStateMachine;

  beforeEach(() => {
    sm = createAgentStateMachine();
  });

  it('auto-transitions exploring → acting on first file edit', () => {
    sm.recordToolCall('write_file', { path: '/a.ts', content: 'hello' });
    expect(sm.getPhase()).toBe('acting');
  });

  it('auto-transitions planning → acting on first file edit', () => {
    sm.transition('planning', 'Plan');
    sm.recordToolCall('edit_file', { path: '/a.ts', old: 'x', new: 'y' });
    expect(sm.getPhase()).toBe('acting');
  });

  it('auto-transitions acting → verifying on test run after edits', () => {
    sm.transition('acting', 'Edit');
    sm.recordToolCall('write_file', { path: '/a.ts', content: 'x' });
    sm.recordToolCall('bash', { command: 'npm test' }, { success: true, output: '' });
    expect(sm.getPhase()).toBe('verifying');
  });

  it('does not auto-transition to verifying without prior edits', () => {
    sm.transition('acting', 'Start');
    sm.recordToolCall('bash', { command: 'npm test' }, { success: true, output: '' });
    expect(sm.getPhase()).toBe('acting');
  });
});

// =============================================================================
// EXPLORATION SATURATION
// =============================================================================

describe('Exploration Saturation', () => {
  it('detects file saturation after threshold', () => {
    const sm = createAgentStateMachine({ explorationFileThreshold: 3 });
    sm.recordToolCall('read_file', { path: '/a.ts' });
    sm.recordToolCall('read_file', { path: '/b.ts' });
    sm.recordToolCall('read_file', { path: '/c.ts' });

    const snapshot = sm.getPhaseSnapshot();
    expect(snapshot.shouldTransition).toBe(true);
  });

  it('does not trigger saturation below threshold', () => {
    const sm = createAgentStateMachine({ explorationFileThreshold: 5 });
    sm.recordToolCall('read_file', { path: '/a.ts' });
    sm.recordToolCall('read_file', { path: '/b.ts' });

    const snapshot = sm.getPhaseSnapshot();
    expect(snapshot.shouldTransition).toBe(false);
  });

  it('detects iteration saturation with diminishing returns', () => {
    const sm = createAgentStateMachine({ explorationIterThreshold: 3 });
    // Read 3 files across 3 iterations, then 3 more iterations with 0 new files
    sm.recordToolCall('read_file', { path: '/a.ts' });
    sm.recordToolCall('read_file', { path: '/b.ts' });
    sm.recordToolCall('read_file', { path: '/a.ts' }); // Resets recentNewFiles at iter 3
    // Now 3 more iterations without new files
    sm.recordToolCall('grep', { pattern: 'foo' });
    sm.recordToolCall('grep', { pattern: 'bar' });

    const snapshot = sm.getPhaseSnapshot();
    expect(snapshot.shouldTransition).toBe(true);
  });

  it('no saturation when not in exploring phase', () => {
    const sm = createAgentStateMachine({ explorationFileThreshold: 2 });
    sm.recordToolCall('read_file', { path: '/a.ts' });
    sm.recordToolCall('read_file', { path: '/b.ts' });
    // Saturation would trigger but we're in acting now
    sm.recordToolCall('write_file', { path: '/c.ts', content: 'x' }); // Transitions to acting
    sm.recordToolCall('read_file', { path: '/d.ts' });

    const snapshot = sm.getPhaseSnapshot();
    expect(snapshot.shouldTransition).toBe(false);
  });
});

// =============================================================================
// BASH FAILURE TRACKING
// =============================================================================

describe('Bash Failure Tracking', () => {
  let sm: AgentStateMachine;

  beforeEach(() => {
    sm = createAgentStateMachine();
    sm.transition('acting', 'Edit');
  });

  it('tracks consecutive bash failures', () => {
    sm.recordToolCall('bash', { command: 'ls' }, { success: false, output: 'error' });
    sm.recordToolCall('bash', { command: 'pwd' }, { success: false, output: 'error' });

    const snapshot = sm.getPhaseSnapshot();
    expect(snapshot.consecutiveBashFailures).toBe(2);
  });

  it('resets on successful bash', () => {
    sm.recordToolCall('bash', { command: 'ls' }, { success: false, output: 'error' });
    sm.recordToolCall('bash', { command: 'pwd' }, { success: true, output: '/home' });

    const snapshot = sm.getPhaseSnapshot();
    expect(snapshot.consecutiveBashFailures).toBe(0);
  });
});

// =============================================================================
// TEST FAILURE CYCLE
// =============================================================================

describe('Test-Fix Cycle', () => {
  let sm: AgentStateMachine;

  beforeEach(() => {
    sm = createAgentStateMachine();
    sm.transition('acting', 'Edit');
    sm.recordToolCall('write_file', { path: '/a.ts', content: 'x' });
  });

  it('enters test-fix cycle after 2 consecutive test failures', () => {
    sm.recordToolCall('bash', { command: 'npm test' }, { success: false, output: 'FAIL' });
    sm.recordToolCall('bash', { command: 'npm test' }, { success: false, output: 'FAIL' });

    const snapshot = sm.getPhaseSnapshot();
    expect(snapshot.inTestFixCycle).toBe(true);
    expect(snapshot.consecutiveTestFailures).toBe(2);
  });

  it('exits test-fix cycle on test success', () => {
    sm.recordToolCall('bash', { command: 'npm test' }, { success: false, output: 'FAIL' });
    sm.recordToolCall('bash', { command: 'npm test' }, { success: false, output: 'FAIL' });
    // Back in acting after the test-fix transition
    sm.recordToolCall('bash', { command: 'npm test' }, { success: true, output: 'PASS' });

    const snapshot = sm.getPhaseSnapshot();
    expect(snapshot.inTestFixCycle).toBe(false);
    expect(snapshot.consecutiveTestFailures).toBe(0);
    expect(snapshot.lastTestPassed).toBe(true);
  });
});

// =============================================================================
// PHASE SNAPSHOT (backward compatibility)
// =============================================================================

describe('Phase Snapshot', () => {
  it('provides a complete snapshot matching economics PhaseState', () => {
    const sm = createAgentStateMachine();
    sm.recordToolCall('read_file', { path: '/a.ts' });
    sm.recordToolCall('grep', { pattern: 'foo', path: '/src' });

    const snapshot = sm.getPhaseSnapshot();
    expect(snapshot.phase).toBe('exploring');
    expect(snapshot.iterationsInPhase).toBe(2);
    expect(snapshot.uniqueFilesRead).toBeInstanceOf(Set);
    expect(snapshot.uniqueFilesRead.size).toBe(1);
    expect(snapshot.uniqueSearches).toBeInstanceOf(Set);
    expect(snapshot.uniqueSearches.size).toBe(1);
    expect(snapshot.filesModified).toBeInstanceOf(Set);
    expect(snapshot.testsRun).toBe(0);
    expect(snapshot.lastTestPassed).toBeNull();
    expect(snapshot.consecutiveTestFailures).toBe(0);
    expect(snapshot.inTestFixCycle).toBe(false);
    expect(snapshot.consecutiveBashFailures).toBe(0);
  });

  it('returns defensive copies of sets', () => {
    const sm = createAgentStateMachine();
    sm.recordToolCall('read_file', { path: '/a.ts' });

    const snapshot1 = sm.getPhaseSnapshot();
    const snapshot2 = sm.getPhaseSnapshot();
    expect(snapshot1.uniqueFilesRead).not.toBe(snapshot2.uniqueFilesRead);
  });
});

// =============================================================================
// RESET
// =============================================================================

describe('Reset', () => {
  it('resets to initial state', () => {
    const sm = createAgentStateMachine();
    sm.recordToolCall('read_file', { path: '/a.ts' });
    sm.transition('acting', 'Edit');
    sm.recordToolCall('write_file', { path: '/b.ts', content: 'x' });

    sm.reset();

    expect(sm.getPhase()).toBe('exploring');
    expect(sm.getTransitions()).toHaveLength(0);
    expect(sm.getPhaseHistory()).toHaveLength(0);
    const snapshot = sm.getPhaseSnapshot();
    expect(snapshot.iterationsInPhase).toBe(0);
    expect(snapshot.uniqueFilesRead.size).toBe(0);
    expect(snapshot.filesModified.size).toBe(0);
  });

  it('reset with custom phase', () => {
    const sm = createAgentStateMachine();
    sm.reset('acting');
    expect(sm.getPhase()).toBe('acting');
  });
});
