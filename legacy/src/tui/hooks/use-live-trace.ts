/**
 * Live Trace Hook
 *
 * Subscribes to agent events in real-time and accumulates iteration-level
 * telemetry for the live dashboard tab. Detects issues such as doom loops,
 * cache hit rate drops, and token spikes as they happen.
 */

import { useState, useEffect, useRef, useCallback } from 'react';

export interface LiveIterationData {
  iteration: number;
  inputTokens: number;
  outputTokens: number;
  cacheHitRate: number;
  toolCalls: string[];
  durationMs: number;
  cost: number;
}

export interface LiveIssue {
  type: string;
  message: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  iteration: number;
  timestamp: Date;
}

export interface LiveDashboardData {
  iterations: LiveIterationData[];
  toolFrequency: Map<string, number>;
  cumulativeTokens: number;
  cumulativeCost: number;
  currentCacheHitRate: number;
  cacheHitRates: number[];
  issues: LiveIssue[];
  isRunning: boolean;
  startTime: Date | null;
}

interface AgentEventEmitter {
  on(event: string, handler: (...args: any[]) => void): void;
  off?(event: string, handler: (...args: any[]) => void): void;
  removeListener?(event: string, handler: (...args: any[]) => void): void;
}

const INITIAL_DATA: LiveDashboardData = {
  iterations: [],
  toolFrequency: new Map(),
  cumulativeTokens: 0,
  cumulativeCost: 0,
  currentCacheHitRate: 0,
  cacheHitRates: [],
  issues: [],
  isRunning: false,
  startTime: null,
};

/**
 * Hook that subscribes to agent events and builds live telemetry data.
 *
 * Listens for `iteration.complete`, `agent.start`, and `agent.end` events
 * from the provided emitter and accumulates per-iteration metrics. Also
 * runs inline issue detection for doom loops, cache drops, and token spikes.
 *
 * @param emitter - An event emitter exposing `on`/`off` or `removeListener` methods,
 *                  or null if no agent is active.
 * @returns Accumulated live dashboard data including iterations, issues, and totals.
 *
 * @example
 * ```tsx
 * const liveData = useLiveTrace(agentEmitter);
 *
 * // Render cumulative cost
 * <Text>Cost: ${liveData.cumulativeCost.toFixed(4)}</Text>
 *
 * // Show issue alerts
 * {liveData.issues.map(issue => (
 *   <Text key={issue.type + issue.iteration} color="red">{issue.message}</Text>
 * ))}
 * ```
 */
export function useLiveTrace(emitter: AgentEventEmitter | null): LiveDashboardData {
  const [data, setData] = useState<LiveDashboardData>(INITIAL_DATA);
  const dataRef = useRef(data);
  dataRef.current = data;

  const detectIssues = useCallback((iterations: LiveIterationData[]): LiveIssue[] => {
    const issues: LiveIssue[] = [];
    const len = iterations.length;
    if (len < 3) return issues;

    // Doom loop detection: same tools called 3+ times in a row
    const last3 = iterations.slice(-3);
    const toolSignatures = last3.map(it => it.toolCalls.sort().join(','));
    if (toolSignatures[0] === toolSignatures[1] && toolSignatures[1] === toolSignatures[2] && toolSignatures[0]) {
      issues.push({
        type: 'doom_loop',
        message: `Same tools called 3x in a row: ${last3[0].toolCalls.join(', ')}`,
        severity: 'high',
        iteration: len,
        timestamp: new Date(),
      });
    }

    // Cache drop detection
    const latest = iterations[len - 1];
    const previous = iterations[len - 2];
    if (previous && latest.cacheHitRate < previous.cacheHitRate * 0.5 && previous.cacheHitRate > 0.3) {
      issues.push({
        type: 'cache_drop',
        message: `Cache hit rate dropped from ${(previous.cacheHitRate * 100).toFixed(0)}% to ${(latest.cacheHitRate * 100).toFixed(0)}%`,
        severity: 'medium',
        iteration: len,
        timestamp: new Date(),
      });
    }

    // Token spike detection
    if (len > 5) {
      const avgTokens = iterations.slice(-6, -1).reduce((s, i) => s + i.inputTokens, 0) / 5;
      if (latest.inputTokens > avgTokens * 2 && avgTokens > 0) {
        issues.push({
          type: 'token_spike',
          message: `Input tokens spiked to ${latest.inputTokens} (avg: ${Math.round(avgTokens)})`,
          severity: 'medium',
          iteration: len,
          timestamp: new Date(),
        });
      }
    }

    return issues;
  }, []);

  useEffect(() => {
    if (!emitter) return;

    const handleIteration = (...args: any[]) => {
      const event = args[0] || {};
      const iterData: LiveIterationData = {
        iteration: event.iteration || dataRef.current.iterations.length + 1,
        inputTokens: event.inputTokens || event.usage?.inputTokens || 0,
        outputTokens: event.outputTokens || event.usage?.outputTokens || 0,
        cacheHitRate: event.cacheHitRate || 0,
        toolCalls: event.toolCalls || [],
        durationMs: event.durationMs || 0,
        cost: event.cost || 0,
      };

      setData(prev => {
        const newIterations = [...prev.iterations, iterData];
        const newToolFreq = new Map(prev.toolFrequency);
        for (const tool of iterData.toolCalls) {
          newToolFreq.set(tool, (newToolFreq.get(tool) || 0) + 1);
        }
        const newIssues = [...prev.issues, ...detectIssues(newIterations)];
        return {
          ...prev,
          iterations: newIterations,
          toolFrequency: newToolFreq,
          cumulativeTokens: prev.cumulativeTokens + iterData.inputTokens + iterData.outputTokens,
          cumulativeCost: prev.cumulativeCost + iterData.cost,
          currentCacheHitRate: iterData.cacheHitRate,
          cacheHitRates: [...prev.cacheHitRates, iterData.cacheHitRate],
          issues: newIssues,
        };
      });
    };

    const handleStart = () => {
      setData(prev => ({ ...prev, isRunning: true, startTime: new Date() }));
    };

    const handleEnd = () => {
      setData(prev => ({ ...prev, isRunning: false }));
    };

    emitter.on('iteration.complete', handleIteration);
    emitter.on('agent.start', handleStart);
    emitter.on('agent.end', handleEnd);

    const cleanup = emitter.off || emitter.removeListener;
    return () => {
      if (cleanup) {
        cleanup.call(emitter, 'iteration.complete', handleIteration);
        cleanup.call(emitter, 'agent.start', handleStart);
        cleanup.call(emitter, 'agent.end', handleEnd);
      }
    };
  }, [emitter, detectIssues]);

  return data;
}
