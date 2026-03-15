import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { FileTreeNode, FileContent } from "@/api/generated/schema";

// Backend returns nested tree with file/directory types — map to frontend shape
interface BackendTreeEntry {
  name: string;
  path: string;
  type: "file" | "directory";
  size: number;
  language: string;
  children: BackendTreeEntry[] | null;
}

function mapEntries(entries: BackendTreeEntry[]): FileTreeNode[] {
  return entries.map((e) => ({
    name: e.name,
    path: e.path,
    type: e.type,
    size: e.size,
    language: e.language || undefined,
    children: e.children ? mapEntries(e.children) : undefined,
  }));
}

export function useFileTree(orgId: string, repoId: string, path = "") {
  return useQuery({
    queryKey: ["files", "tree", orgId, repoId, path],
    queryFn: async () => {
      const url = path
        ? `/api/v2/projects/${repoId}/tree/${path}`
        : `/api/v2/projects/${repoId}/tree?recursive=true`;
      const res = await apiFetch<{
        path: string;
        ref: string;
        entries: BackendTreeEntry[];
      }>(url);
      return { tree: mapEntries(res.entries) };
    },
    enabled: !!repoId,
  });
}

export function useFileContent(orgId: string, repoId: string, path: string) {
  return useQuery({
    queryKey: ["files", "content", orgId, repoId, path],
    queryFn: async () => {
      const res = await apiFetch<{
        path: string;
        ref: string;
        content: string;
        language: string;
        size_bytes: number;
        line_count: number;
      }>(`/api/v2/projects/${repoId}/files/${path}`);
      return {
        path: res.path,
        content: res.content,
        language: res.language,
        size: res.size_bytes,
        lines: res.line_count,
        encoding: "utf-8",
      } as FileContent;
    },
    enabled: !!repoId && !!path,
  });
}

export function useRepoStats(orgId: string, repoId: string) {
  return useQuery({
    queryKey: ["files", "stats", orgId, repoId],
    queryFn: () =>
      apiFetch<{
        total_files: number;
        total_symbols: number;
        languages: Record<string, number>;
        embedded_files: number;
      }>(`/api/v2/projects/${repoId}/stats`),
    enabled: !!repoId,
  });
}
