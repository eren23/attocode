import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type {
  EmbeddingStatus,
  EmbeddingFileEntry,
  IndexingStatus,
} from "@/api/generated/schema";

export interface SimilarFileResult {
  file_path: string;
  score: number;
  snippet: string;
}

interface FindSimilarResponse {
  source_file: string;
  similar: SimilarFileResult[];
}

export function useEmbeddingStatus(repoId: string) {
  return useQuery({
    queryKey: ["embeddings", "status", repoId],
    queryFn: async () => {
      const res = await apiFetch<{
        total_files: number;
        embedded_files: number;
        coverage_pct: number;
        model: string;
        provider_available?: boolean;
        provider_hint?: string;
      }>(`/api/v2/projects/${repoId}/embeddings/status`);
      return {
        total_files: res.total_files,
        embedded_files: res.embedded_files,
        coverage: res.coverage_pct / 100,
        last_updated: null,
        provider_available: res.provider_available,
        provider_hint: res.provider_hint,
      } as EmbeddingStatus;
    },
    enabled: !!repoId,
    refetchInterval: 10000,
  });
}

export function useEmbeddingFiles(repoId: string, search: string = "") {
  return useQuery({
    queryKey: ["embeddings", "files", repoId, search],
    queryFn: async () => {
      const params = search ? `?search=${encodeURIComponent(search)}` : "";
      const res = await apiFetch<{
        files: { path: string; content_sha: string; has_embedding: boolean; chunk_count?: number; last_embedded_at?: string | null }[];
        total: number;
      }>(`/api/v2/projects/${repoId}/embeddings/files${params}`);
      return {
        files: res.files.map((f) => ({
          file: f.path,
          content_sha: f.content_sha,
          embedded: f.has_embedding,
          chunk_count: f.chunk_count ?? 0,
          last_embedded_at: f.last_embedded_at ?? null,
        })) as EmbeddingFileEntry[],
        total: res.total,
      };
    },
    enabled: !!repoId,
  });
}

export function useIndexingStatus(repoId: string) {
  return useQuery({
    queryKey: ["embeddings", "indexing", repoId],
    queryFn: async () => {
      const res = await apiFetch<{
        index_status: string;
        last_indexed_at: string | null;
        active_jobs: number;
        embedding_coverage_pct: number;
        total_files: number;
        embedded_files: number;
      }>(`/api/v2/projects/${repoId}/indexing/status`);
      return {
        status: res.index_status,
        progress: res.embedding_coverage_pct,
        files_processed: res.embedded_files,
        files_total: res.total_files,
        started_at: null,
        completed_at: res.last_indexed_at,
      } as IndexingStatus;
    },
    enabled: !!repoId,
    refetchInterval: 5000,
  });
}

export function useTriggerEmbedding(repoId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<{ job_id: string; status: string; message: string }>(
        `/api/v2/projects/${repoId}/embeddings/generate`,
        {
          method: "POST",
          body: JSON.stringify({ branch: "main" }),
        },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["embeddings", "status", repoId] });
      qc.invalidateQueries({ queryKey: ["embeddings", "indexing", repoId] });
    },
  });
}

export function useFindSimilar(repoId: string) {
  return useMutation({
    mutationFn: (contentSha: string) =>
      apiFetch<FindSimilarResponse>(
        `/api/v2/projects/${repoId}/embeddings/similar?content_sha=${encodeURIComponent(contentSha)}`,
        { method: "POST" },
      ),
  });
}
