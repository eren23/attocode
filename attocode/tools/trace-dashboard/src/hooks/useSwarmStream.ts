/**
 * useSwarmStream Hook
 *
 * Connects to the SSE endpoint and maintains live swarm state.
 * Accepts an optional `dir` param to select which swarm-live directory to watch.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import type { SwarmLiveState, TimestampedSwarmEvent } from '../lib/swarm-types';

const MAX_RECENT_EVENTS = 200;
const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 30000;

export interface UseSwarmStreamResult {
  connected: boolean;
  active: boolean;
  idle: boolean;
  state: SwarmLiveState | null;
  recentEvents: TimestampedSwarmEvent[];
  error: Error | null;
  reconnect: () => void;
}

function buildUrl(base: string, params: Record<string, string | undefined>): string {
  const url = new URL(base, window.location.origin);
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined) url.searchParams.set(k, v);
  }
  return url.pathname + url.search;
}

export function useSwarmStream(dir?: string): UseSwarmStreamResult {
  const [connected, setConnected] = useState(false);
  const [state, setState] = useState<SwarmLiveState | null>(null);
  const [recentEvents, setRecentEvents] = useState<TimestampedSwarmEvent[]>([]);
  const [error, setError] = useState<Error | null>(null);
  const [initialFetchDone, setInitialFetchDone] = useState(false);

  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectAttemptRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastSeqRef = useRef(0);
  const dirRef = useRef(dir);
  dirRef.current = dir;

  const connect = useCallback(() => {
    // Clean up existing connection
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }

    const sseUrl = buildUrl('/api/swarm/stream', {
      since: String(lastSeqRef.current),
      dir: dirRef.current,
    });
    const es = new EventSource(sseUrl);
    eventSourceRef.current = es;

    es.onopen = () => {
      setConnected(true);
      setError(null);
      reconnectAttemptRef.current = 0;
    };

    es.addEventListener('swarm-state', (e) => {
      try {
        const newState = JSON.parse(e.data);
        // Handle idle state from server (no swarm-live dir found)
        if (newState.idle && !newState.tasks) {
          setInitialFetchDone(true);
          return;
        }
        setState(newState as SwarmLiveState);
        setInitialFetchDone(true);
        if (newState.lastSeq > lastSeqRef.current) {
          lastSeqRef.current = newState.lastSeq;
        }
      } catch {
        // Malformed state
      }
    });

    es.addEventListener('swarm-event', (e) => {
      try {
        const event: TimestampedSwarmEvent = JSON.parse(e.data);
        if (event.seq > lastSeqRef.current) {
          lastSeqRef.current = event.seq;
        }
        setRecentEvents((prev) => {
          const next = [...prev, event];
          return next.length > MAX_RECENT_EVENTS ? next.slice(-MAX_RECENT_EVENTS) : next;
        });

        // Also update state from events when possible
        updateStateFromEvent(event, setState);
      } catch {
        // Malformed event
      }
    });

    es.addEventListener('heartbeat', () => {
      // Keep-alive, no action needed
    });

    es.onerror = () => {
      setConnected(false);
      es.close();
      eventSourceRef.current = null;

      // Exponential backoff reconnect
      const attempt = reconnectAttemptRef.current++;
      const delay = Math.min(RECONNECT_BASE_MS * Math.pow(2, attempt), RECONNECT_MAX_MS);

      setError(new Error(`Connection lost. Reconnecting in ${(delay / 1000).toFixed(0)}s...`));

      reconnectTimerRef.current = setTimeout(() => {
        connect();
      }, delay);
    };
  }, []);

  const reconnect = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    reconnectAttemptRef.current = 0;
    connect();
  }, [connect]);

  // Initial fetch of state (in case SSE hasn't connected yet)
  useEffect(() => {
    const stateUrl = buildUrl('/api/swarm/state', { dir });
    fetch(stateUrl)
      .then((res) => res.json())
      .then((data) => {
        if (data.success && data.data) {
          setState(data.data);
          if (data.data.lastSeq > lastSeqRef.current) {
            lastSeqRef.current = data.data.lastSeq;
          }
        }
        setInitialFetchDone(true);
      })
      .catch(() => {
        // Initial fetch failed; SSE will provide data
        setInitialFetchDone(true);
      });
  }, [dir]);

  // Connect SSE on mount and reconnect when dir changes
  useEffect(() => {
    // Reset state when dir changes
    setState(null);
    setRecentEvents([]);
    setError(null);
    setInitialFetchDone(false);
    lastSeqRef.current = 0;
    reconnectAttemptRef.current = 0;

    connect();
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
    };
  }, [connect, dir]);

  // idle = initial fetch done but no state received (no active swarm)
  const idle = initialFetchDone && !state;

  return {
    connected,
    active: state?.active ?? false,
    idle,
    state,
    recentEvents,
    error,
    reconnect,
  };
}

/**
 * Update state incrementally from individual events.
 */
function updateStateFromEvent(
  event: TimestampedSwarmEvent,
  setState: React.Dispatch<React.SetStateAction<SwarmLiveState | null>>
): void {
  const e = event.event;

  setState((prev) => {
    if (!prev) return prev;

    switch (e.type) {
      case 'swarm.task.dispatched': {
        const tasks = prev.tasks.map((t) =>
          t.id === e.taskId ? { ...t, status: 'dispatched' as const, assignedModel: e.model as string, dispatchedAt: Date.now() } : t
        );
        return { ...prev, tasks, lastSeq: event.seq };
      }

      case 'swarm.task.completed': {
        const tasks = prev.tasks.map((t) =>
          t.id === e.taskId
            ? {
                ...t,
                status: 'completed' as const,
                result: {
                  success: e.success as boolean,
                  output: '',
                  tokensUsed: e.tokensUsed as number,
                  costUsed: e.costUsed as number,
                  durationMs: e.durationMs as number,
                  qualityScore: e.qualityScore as number | undefined,
                  model: t.assignedModel ?? '',
                },
              }
            : t
        );
        return { ...prev, tasks, lastSeq: event.seq };
      }

      case 'swarm.task.failed': {
        if (!(e.willRetry as boolean)) {
          const tasks = prev.tasks.map((t) =>
            t.id === e.taskId ? { ...t, status: 'failed' as const } : t
          );
          return { ...prev, tasks, lastSeq: event.seq };
        }
        return { ...prev, lastSeq: event.seq };
      }

      case 'swarm.task.skipped': {
        const tasks = prev.tasks.map((t) =>
          t.id === e.taskId ? { ...t, status: 'skipped' as const } : t
        );
        return { ...prev, tasks, lastSeq: event.seq };
      }

      case 'swarm.quality.rejected': {
        const tasks = prev.tasks.map((t) =>
          t.id === e.taskId
            ? {
                ...t,
                retryContext: {
                  previousFeedback: e.feedback as string,
                  previousScore: e.score as number,
                  attempt: t.attempts,
                },
              }
            : t
        );
        return { ...prev, tasks, lastSeq: event.seq };
      }

      case 'swarm.budget.update': {
        const status = prev.status
          ? {
              ...prev.status,
              budget: {
                tokensUsed: e.tokensUsed as number,
                tokensTotal: e.tokensTotal as number,
                costUsed: e.costUsed as number,
                costTotal: e.costTotal as number,
              },
            }
          : prev.status;
        return { ...prev, status, lastSeq: event.seq };
      }

      default:
        return { ...prev, lastSeq: event.seq };
    }
  });
}
