import { useMutation, useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { DependencyGraphResponse } from "@/api/generated/schema";

export function useDependencyGraph(repoId: string) {
  return useMutation({
    mutationFn: (opts: { file?: string; depth?: number; directory?: string }) =>
      apiFetch<DependencyGraphResponse>(
        `/api/v2/projects/${repoId}/dependency-graph`,
        {
          method: "POST",
          body: JSON.stringify({
            start_file: opts.file || "",
            depth: opts.depth || 3,
            directory: opts.directory || "",
          }),
        },
      ),
  });
}

export function useGraphQuery(repoId: string) {
  return useMutation({
    mutationFn: (query: string) =>
      apiFetch<DependencyGraphResponse>(
        `/api/v2/projects/${repoId}/graph/query`,
        {
          method: "POST",
          body: JSON.stringify({ file: query }),
        },
      ),
  });
}

export function useRelatedFiles(repoId: string, file: string) {
  return useQuery({
    queryKey: ["graph", "related", repoId, file],
    queryFn: () =>
      apiFetch<{ file: string; related: { path: string; score: number; relation_type: string }[] }>(
        `/api/v2/projects/${repoId}/graph/related`,
        {
          method: "POST",
          body: JSON.stringify({ file }),
        },
      ),
    enabled: !!repoId && !!file,
  });
}
