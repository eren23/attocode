import { useMutation, useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { SearchResultsResponse } from "@/api/generated/schema";

export function useSearch(repoId: string, query: string) {
  return useQuery({
    queryKey: ["search", repoId, query],
    queryFn: () =>
      apiFetch<SearchResultsResponse>(`/api/v2/projects/${repoId}/search`, {
        method: "POST",
        body: JSON.stringify({ query, limit: 50 }),
      }),
    enabled: !!repoId && !!query,
  });
}

export function useSearchMutation(repoId: string) {
  return useMutation({
    mutationFn: (query: string) =>
      apiFetch<SearchResultsResponse>(`/api/v2/projects/${repoId}/search`, {
        method: "POST",
        body: JSON.stringify({ query, limit: 50 }),
      }),
  });
}
