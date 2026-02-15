import { describe, expect, it, vi } from 'vitest';
import type { AgentResult } from '../../src/types.js';
import { runWithIncompleteAutoLoop } from '../../src/tui/app.js';

function makeResult(partial: Partial<AgentResult>): AgentResult {
  return {
    success: true,
    response: 'ok',
    metrics: {
      totalTokens: 0,
      inputTokens: 0,
      outputTokens: 0,
      estimatedCost: 0,
      llmCalls: 0,
      toolCalls: 0,
      duration: 0,
    },
    messages: [],
    completion: {
      success: true,
      reason: 'completed',
    },
    ...partial,
  };
}

describe('runWithIncompleteAutoLoop', () => {
  it('retries once and recovers from future_intent to completed', async () => {
    const run = vi.fn<(task: string) => Promise<AgentResult>>()
      .mockResolvedValueOnce(makeResult({
        success: false,
        error: 'pending',
        response: 'I will now fix it',
        completion: { success: false, reason: 'future_intent', details: 'pending work' },
      }))
      .mockResolvedValueOnce(makeResult({
        success: true,
        response: 'Done.',
        completion: { success: true, reason: 'completed' },
      }));

    const retries: Array<{ attempt: number; maxAttempts: number }> = [];
    const { result, autoLoopRuns, reasonChain } = await runWithIncompleteAutoLoop(
      {
        run,
        getResilienceConfig: () => ({
          incompleteActionAutoLoop: true,
          maxIncompleteAutoLoops: 2,
          autoLoopPromptStyle: 'strict',
        }),
      },
      'initial task',
      {
        onRetry: (attempt, maxAttempts) => retries.push({ attempt, maxAttempts }),
      },
    );

    expect(run).toHaveBeenCalledTimes(2);
    expect(result.success).toBe(true);
    expect(autoLoopRuns).toBe(1);
    expect(reasonChain).toEqual(['future_intent', 'completed']);
    expect(retries).toEqual([{ attempt: 1, maxAttempts: 2 }]);
    expect(result.completion.recovery?.autoLoopRuns).toBe(1);
  });

  it('stops after maxIncompleteAutoLoops and remains incomplete', async () => {
    const run = vi.fn<(task: string) => Promise<AgentResult>>()
      .mockResolvedValue(makeResult({
        success: false,
        error: 'pending',
        response: 'Let me do it',
        completion: { success: false, reason: 'incomplete_action', details: 'still pending' },
      }));

    const { result, autoLoopRuns, reasonChain, maxIncompleteAutoLoops } = await runWithIncompleteAutoLoop(
      {
        run,
        getResilienceConfig: () => ({
          incompleteActionAutoLoop: true,
          maxIncompleteAutoLoops: 2,
          autoLoopPromptStyle: 'strict',
        }),
      },
      'initial task',
    );

    expect(maxIncompleteAutoLoops).toBe(2);
    expect(autoLoopRuns).toBe(2);
    expect(run).toHaveBeenCalledTimes(3);
    expect(result.success).toBe(false);
    expect(reasonChain).toEqual(['incomplete_action', 'incomplete_action', 'incomplete_action']);
    expect(result.completion.recovery?.terminal).toBe(true);
  });

  it('does not retry when incomplete auto-loop is disabled', async () => {
    const run = vi.fn<(task: string) => Promise<AgentResult>>()
      .mockResolvedValueOnce(makeResult({
        success: false,
        error: 'pending',
        response: 'I will do it',
        completion: { success: false, reason: 'future_intent', details: 'pending work' },
      }));

    const { result, autoLoopRuns } = await runWithIncompleteAutoLoop(
      {
        run,
        getResilienceConfig: () => ({
          incompleteActionAutoLoop: false,
        }),
      },
      'initial task',
    );

    expect(run).toHaveBeenCalledTimes(1);
    expect(autoLoopRuns).toBe(0);
    expect(result.success).toBe(false);
    expect(result.completion.recovery?.reasonChain).toEqual(['future_intent']);
  });
});
