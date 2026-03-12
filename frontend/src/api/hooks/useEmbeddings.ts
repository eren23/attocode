import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type {
  EmbeddingStatus,
  EmbeddingFileEntry,
  IndexingStatus,
} from "@/api/generated/schema";

export function useEmbeddingStatus(repoId: string) {
  return useQuery({
    queryKey: ["embeddings", "status", repoId],
    queryFn: () =>
      apiFetch<EmbeddingStatus>(
        `/api/v1/orgs/_/repos/${repoId}/embeddings/status`,
      ),
    enabled: !!repoId,
    refetchInterval: 10000,
  });
}

export function useEmbeddingFiles(repoId: string) {
  return useQuery({
    queryKey: ["embeddings", "files", repoId],
    queryFn: () =>
      apiFetch<{ files: EmbeddingFileEntry[] }>(
        `/api/v1/orgs/_/repos/${repoId}/embeddings/files`,
      ),
    enabled: !!repoId,
  });
}

export function useIndexingStatus(repoId: string) {
  return useQuery({
    queryKey: ["embeddings", "indexing", repoId],
    queryFn: () =>
      apiFetch<IndexingStatus>(
        `/api/v1/orgs/_/repos/${repoId}/embeddings/indexing`,
      ),
    enabled: !!repoId,
    refetchInterval: 5000,
  });
}

export function useTriggerEmbedding(repoId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (files?: string[]) =>
      apiFetch<{ detail: string }>(
        `/api/v1/orgs/_/repos/${repoId}/embeddings/trigger`,
        {
          method: "POST",
          body: JSON.stringify({ files }),
        },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["embeddings", "status", repoId] });
      qc.invalidateQueries({ queryKey: ["embeddings", "indexing", repoId] });
    },
  });
}
