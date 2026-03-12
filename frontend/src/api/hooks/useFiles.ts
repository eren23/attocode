import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { FileTreeNode, FileContent } from "@/api/generated/schema";

export function useFileTree(orgId: string, repoId: string, path = "") {
  return useQuery({
    queryKey: ["files", "tree", orgId, repoId, path],
    queryFn: () => {
      const params = new URLSearchParams();
      if (path) params.set("path", path);
      // Use v2 files endpoint that returns structured JSON
      return apiFetch<{ tree: FileTreeNode[] }>(
        `/api/v2/projects/${repoId}/tree?${params}`,
      );
    },
    enabled: !!repoId,
  });
}

export function useFileContent(orgId: string, repoId: string, path: string) {
  return useQuery({
    queryKey: ["files", "content", orgId, repoId, path],
    queryFn: () =>
      apiFetch<FileContent>(`/api/v2/projects/${repoId}/files/${path}`),
    enabled: !!repoId && !!path,
  });
}

export function useRepoStats(orgId: string, repoId: string) {
  return useQuery({
    queryKey: ["files", "stats", orgId, repoId],
    queryFn: () =>
      apiFetch<{
        total_files: number;
        total_lines: number;
        languages: Record<string, number>;
      }>(`/api/v2/projects/${repoId}/stats`),
    enabled: !!repoId,
  });
}
