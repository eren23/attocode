/**
 * API Hooks
 *
 * React hooks for fetching data from the trace dashboard API.
 */

import { useState, useEffect, useCallback } from 'react';
import type { TimelineEntry, TreeNode, SwarmActivityData } from '../lib/types';
import type { SessionListItem } from '../api/trace-service';
import type { TraceSummary } from '../lib/output/json-exporter';
import type { TokenFlowViewData } from '../lib/views/token-flow-view';

// API response wrapper
interface ApiResponse<T> {
  success: boolean;
  data?: T;
  error?: string;
}

// Alias for consistency
type SessionSummary = TraceSummary;
type TokenFlowData = TokenFlowViewData;

// Extended comparison result returned by the API
interface CompareResult {
  baselineId: string;
  comparisonId: string;
  baseline: TraceSummary;
  comparison: TraceSummary;
  metricDiffs: {
    iterations: number;
    tokens: number;
    cost: number;
    cacheHitRate: number;
    errors: number;
  };
  percentChanges: {
    iterations: number;
    tokens: number;
    cost: number;
    cacheHitRate: number;
  };
  regressions: string[];
  improvements: string[];
  assessment: 'improved' | 'regressed' | 'mixed' | 'similar';
}

const API_BASE = '/api';

async function fetchApi<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    throw new Error(`API error: ${response.status} ${response.statusText}`);
  }
  const data: ApiResponse<T> = await response.json();
  if (!data.success) {
    throw new Error(data.error || 'Unknown error');
  }
  return data.data as T;
}

interface UseApiResult<T> {
  data: T | null;
  loading: boolean;
  error: Error | null;
  refetch: () => void;
}

function useApi<T>(path: string | null): UseApiResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const fetchData = useCallback(async () => {
    if (!path) {
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const result = await fetchApi<T>(path);
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err : new Error('Unknown error'));
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  return { data, loading, error, refetch: fetchData };
}

// Typed hooks for specific endpoints

export function useSessions() {
  return useApi<SessionListItem[]>('/sessions');
}

export function useSession(id: string | undefined) {
  return useApi<SessionSummary>(id ? `/sessions/${encodeURIComponent(id)}` : null);
}

export function useTimeline(id: string | undefined) {
  return useApi<{ startTime: string; totalDuration: number; entries: TimelineEntry[] }>(
    id ? `/sessions/${encodeURIComponent(id)}/timeline` : null
  );
}

export function useTree(id: string | undefined) {
  return useApi<{ root: TreeNode }>(id ? `/sessions/${encodeURIComponent(id)}/tree` : null);
}

export function useTokens(id: string | undefined) {
  return useApi<TokenFlowData>(id ? `/sessions/${encodeURIComponent(id)}/tokens` : null);
}

export function useIssues(id: string | undefined) {
  return useApi<Array<{ id: string; type: string; severity: string; description: string; evidence: string }>>(
    id ? `/sessions/${encodeURIComponent(id)}/issues` : null
  );
}

export function useSwarmData(id: string | undefined) {
  return useApi<SwarmActivityData>(id ? `/sessions/${encodeURIComponent(id)}/swarm` : null);
}

export function useCompare(idA: string | undefined, idB: string | undefined) {
  const path = idA && idB
    ? `/compare?a=${encodeURIComponent(idA)}&b=${encodeURIComponent(idB)}`
    : null;
  return useApi<CompareResult>(path);
}
