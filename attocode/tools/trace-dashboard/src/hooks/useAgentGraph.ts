/**
 * useAgentGraph Hook
 *
 * Fetches agent graph data for a given session.
 */

import { useState, useEffect, useCallback } from 'react';
import type { AgentGraphData } from '../lib/agent-graph-types';

interface UseAgentGraphResult {
  data: AgentGraphData | null;
  loading: boolean;
  error: Error | null;
  refetch: () => void;
}

export function useAgentGraph(sessionId?: string): UseAgentGraphResult {
  const [data, setData] = useState<AgentGraphData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const fetchData = useCallback(async () => {
    if (!sessionId) {
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/agents`);
      if (!res.ok) {
        throw new Error(`API error: ${res.status} ${res.statusText}`);
      }
      const json = await res.json();
      if (!json.success) {
        throw new Error(json.error || 'Failed to fetch agent graph');
      }
      setData(json.data as AgentGraphData);
    } catch (err) {
      setError(err instanceof Error ? err : new Error('Unknown error'));
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  return { data, loading, error, refetch: fetchData };
}
