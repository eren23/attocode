/**
 * useCodeMap - Hook for fetching code map data from the API
 */

import { useState, useEffect, useCallback } from 'react';
import type { CodeMapData } from '../lib/codemap-types';

interface ApiResponse<T> {
  success: boolean;
  data?: T;
  error?: string;
}

const API_BASE = '/api';

interface UseCodeMapResult {
  data: CodeMapData | null;
  loading: boolean;
  error: Error | null;
  refetch: () => void;
}

export interface UseCodeMapOptions {
  all?: boolean;
  limit?: number;
  exclude?: string[];
}

const DEFAULT_EXCLUDE = ['node_modules', 'dist', '.next', 'build', 'coverage'];

export function useCodeMap(sessionId?: string, options: UseCodeMapOptions = {}): UseCodeMapResult {
  const [data, setData] = useState<CodeMapData | null>(null);
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
      const params = new URLSearchParams();
      if (options.all) {
        params.set('all', '1');
      } else {
        params.set('limit', String(options.limit ?? 350));
        const exclude = options.exclude && options.exclude.length > 0
          ? options.exclude
          : DEFAULT_EXCLUDE;
        params.set('exclude', exclude.join(','));
      }

      const query = params.toString();
      const response = await fetch(
        `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/codemap${query ? `?${query}` : ''}`
      );
      if (!response.ok) {
        throw new Error(`API error: ${response.status} ${response.statusText}`);
      }
      const json: ApiResponse<CodeMapData> = await response.json();
      if (!json.success) {
        throw new Error(json.error || 'Unknown error');
      }
      setData(json.data as CodeMapData);
    } catch (err) {
      setError(err instanceof Error ? err : new Error('Unknown error'));
    } finally {
      setLoading(false);
    }
  }, [sessionId, options.all, options.limit, options.exclude]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  return { data, loading, error, refetch: fetchData };
}
