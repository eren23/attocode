/**
 * Async Subagent Tests
 */

import { describe, it, expect, afterEach } from 'vitest';
import {
  createSubagentHandle,
  SubagentSupervisor,
  createSubagentSupervisor,
} from '../src/integrations/agents/async-subagent.js';

function makeSuccessResult() {
  return {
    success: true as const,
    output: 'done',
    metrics: { tokens: 100, duration: 1000, toolCalls: 5 },
  };
}

function makeFailResult() {
  return {
    success: false as const,
    output: 'failed',
    metrics: { tokens: 50, duration: 500, toolCalls: 2 },
  };
}

describe('createSubagentHandle', () => {
  it('should create a handle with correct metadata', () => {
    const handle = createSubagentHandle(
      'h1', 'researcher', 'analyze code',
      Promise.resolve(makeSuccessResult()),
      {},
    );
    expect(handle.id).toBe('h1');
    expect(handle.agentName).toBe('researcher');
    expect(handle.task).toBe('analyze code');
    expect(handle.startedAt).toBeGreaterThan(0);
  });

  it('should report running until completion', async () => {
    let resolve!: (v: ReturnType<typeof makeSuccessResult>) => void;
    const promise = new Promise<ReturnType<typeof makeSuccessResult>>(r => { resolve = r; });

    const handle = createSubagentHandle('h2', 'coder', 'write code', promise, {});
    expect(handle.isRunning()).toBe(true);

    resolve(makeSuccessResult());
    await handle.completion;
    expect(handle.isRunning()).toBe(false);
  });

  it('should handle failed spawn promises', async () => {
    const promise = Promise.reject(new Error('spawn failed'));
    const handle = createSubagentHandle('h3', 'test', 'task', promise, {});

    const result = await handle.completion;
    expect(result.success).toBe(false);
    expect(result.output).toContain('spawn failed');
    expect(handle.isRunning()).toBe(false);
  });

  it('should forward requestWrapup to controls', () => {
    let wrapupCalled = false;
    const handle = createSubagentHandle(
      'h4', 'test', 'task',
      new Promise(() => {}), // never resolves
      { requestWrapup: () => { wrapupCalled = true; } },
    );
    handle.requestWrapup('timeout');
    expect(wrapupCalled).toBe(true);
  });

  it('should forward cancel to controls', () => {
    let cancelCalled = false;
    const handle = createSubagentHandle(
      'h5', 'test', 'task',
      new Promise(() => {}),
      { cancel: () => { cancelCalled = true; } },
    );
    handle.cancel();
    expect(cancelCalled).toBe(true);
  });

  it('should return default progress when no getProgress control', () => {
    const handle = createSubagentHandle(
      'h6', 'test', 'task',
      new Promise(() => {}),
      {},
    );
    const progress = handle.getProgress();
    expect(progress.iterations).toBe(0);
    expect(progress.toolCalls).toBe(0);
    expect(progress.elapsedMs).toBeGreaterThanOrEqual(0);
  });

  it('should return result-based progress after completion', async () => {
    const handle = createSubagentHandle(
      'h7', 'test', 'task',
      Promise.resolve(makeSuccessResult()),
      {},
    );
    await handle.completion;
    const progress = handle.getProgress();
    expect(progress.toolCalls).toBe(5);
    expect(progress.tokensUsed).toBe(100);
  });

  it('should accept onProgress callbacks', () => {
    const handle = createSubagentHandle(
      'h8', 'test', 'task',
      new Promise(() => {}),
      {},
    );
    let called = false;
    handle.onProgress(() => { called = true; });
    // Callbacks are registered but not auto-invoked by the handle itself
    expect(called).toBe(false);
  });
});

describe('SubagentSupervisor', () => {
  let supervisor: SubagentSupervisor;

  afterEach(() => {
    supervisor?.stop();
  });

  it('should add and track handles', () => {
    supervisor = new SubagentSupervisor({ checkIntervalMs: 100000 });
    const handle = createSubagentHandle(
      's1', 'test', 'task',
      new Promise(() => {}),
      {},
    );
    supervisor.add(handle);
    expect(supervisor.getActive()).toHaveLength(1);
  });

  it('should remove handles', () => {
    supervisor = new SubagentSupervisor({ checkIntervalMs: 100000 });
    const handle = createSubagentHandle(
      's2', 'test', 'task',
      new Promise(() => {}),
      {},
    );
    supervisor.add(handle);
    supervisor.remove('s2');
    expect(supervisor.getActive()).toHaveLength(0);
  });

  it('should separate active from completed', async () => {
    supervisor = new SubagentSupervisor({ checkIntervalMs: 100000 });
    const done = createSubagentHandle(
      's3', 'test', 'done',
      Promise.resolve(makeSuccessResult()),
      {},
    );
    await done.completion;

    const running = createSubagentHandle(
      's4', 'test', 'running',
      new Promise(() => {}),
      {},
    );

    supervisor.add(done);
    supervisor.add(running);

    expect(supervisor.getCompleted()).toHaveLength(1);
    expect(supervisor.getActive()).toHaveLength(1);
  });

  it('should waitAll for all handles', async () => {
    supervisor = new SubagentSupervisor({ checkIntervalMs: 100000 });
    const h1 = createSubagentHandle('w1', 'a', 't', Promise.resolve(makeSuccessResult()), {});
    const h2 = createSubagentHandle('w2', 'b', 't', Promise.resolve(makeFailResult()), {});

    supervisor.add(h1);
    supervisor.add(h2);

    const results = await supervisor.waitAll();
    expect(results).toHaveLength(2);
    expect(results[0].success).toBe(true);
    expect(results[1].success).toBe(false);
  });

  it('should waitAny for first completed', async () => {
    supervisor = new SubagentSupervisor({ checkIntervalMs: 100000 });
    const fast = createSubagentHandle('f1', 'fast', 't', Promise.resolve(makeSuccessResult()), {});
    const slow = createSubagentHandle('f2', 'slow', 't', new Promise(() => {}), {});

    supervisor.add(fast);
    supervisor.add(slow);

    const { handle, result } = await supervisor.waitAny();
    expect(handle.id).toBe('f1');
    expect(result.success).toBe(true);
  });

  it('should cancelAll running agents', () => {
    supervisor = new SubagentSupervisor({ checkIntervalMs: 100000 });
    let cancelled = 0;
    const h1 = createSubagentHandle('c1', 'a', 't', new Promise(() => {}), {
      cancel: () => { cancelled++; },
    });
    const h2 = createSubagentHandle('c2', 'b', 't', new Promise(() => {}), {
      cancel: () => { cancelled++; },
    });

    supervisor.add(h1);
    supervisor.add(h2);
    supervisor.cancelAll();
    expect(cancelled).toBe(2);
  });

  it('should stop and clear all handles', () => {
    supervisor = new SubagentSupervisor({ checkIntervalMs: 100000 });
    supervisor.add(createSubagentHandle('x1', 'a', 't', new Promise(() => {}), {}));
    supervisor.stop();
    expect(supervisor.getActive()).toHaveLength(0);
  });
});

describe('createSubagentSupervisor', () => {
  it('should create a supervisor with defaults', () => {
    const s = createSubagentSupervisor();
    expect(s).toBeInstanceOf(SubagentSupervisor);
    s.stop();
  });
});
