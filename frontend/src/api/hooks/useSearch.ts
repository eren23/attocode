import { useMutation, useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { SearchResult, SearchResultsResponse } from "@/api/generated/schema";

// Backend returns different field names than the frontend schema
interface BackendSearchResult {
  file_path: string;
  snippet: string;
  score: number;
  line: number | null;
}

interface BackendSearchResponse {
  query: string;
  results: BackendSearchResult[];
  total: number;
}

function mapResult(r: BackendSearchResult): SearchResult {
  return {
    file: r.file_path,
    line: r.line ?? 0,
    content: r.snippet,
    score: r.score,
  };
}

function mapResponse(res: BackendSearchResponse): SearchResultsResponse {
  return {
    query: res.query,
    results: res.results.map(mapResult),
    total: res.total,
    took_ms: 0,
  };
}

export function useSearch(
  repoId: string,
  query: string,
  options?: { topK?: number; fileFilter?: string },
) {
  const topK = options?.topK ?? 50;
  const fileFilter = options?.fileFilter ?? "";
  return useQuery({
    queryKey: ["search", repoId, query, topK, fileFilter],
    queryFn: async () => {
      const body: Record<string, unknown> = { query, top_k: topK };
      if (fileFilter) body.file_filter = fileFilter;
      const res = await apiFetch<BackendSearchResponse>(
        `/api/v2/projects/${repoId}/search`,
        {
          method: "POST",
          body: JSON.stringify(body),
        },
      );
      return mapResponse(res);
    },
    enabled: !!repoId && !!query && query.length >= 2,
    staleTime: 30_000,
  });
}

export function useSearchMutation(repoId: string) {
  return useMutation({
    mutationFn: async (query: string) => {
      const res = await apiFetch<BackendSearchResponse>(
        `/api/v2/projects/${repoId}/search`,
        {
          method: "POST",
          body: JSON.stringify({ query, top_k: 50 }),
        },
      );
      return mapResponse(res);
    },
  });
}
