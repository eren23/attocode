import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type {
  LearningListResponse,
  LearningRecallResponse,
} from "@/api/generated/schema";

interface LearningTextResult {
  result: string;
}

export function useLearnings(repoId: string, opts?: { status?: string; type?: string; scope?: string }) {
  return useQuery({
    queryKey: ["learnings", "list", repoId, opts],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (opts?.status) params.set("status", opts.status);
      if (opts?.type) params.set("type", opts.type);
      if (opts?.scope) params.set("scope", opts.scope);
      const res = await apiFetch<LearningListResponse>(
        `/api/v2/projects/${repoId}/learnings?${params}`,
      );
      return res.learnings;
    },
    enabled: !!repoId,
  });
}

export function useRecallLearnings(repoId: string) {
  return useMutation({
    mutationFn: async (query: string) => {
      const params = new URLSearchParams({ query });
      return apiFetch<LearningRecallResponse>(
        `/api/v2/projects/${repoId}/learnings/recall?${params}`,
      );
    },
  });
}

export function useRecordLearning(repoId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      type: string;
      description: string;
      details?: string;
      scope?: string;
      confidence?: number;
    }) =>
      apiFetch<LearningTextResult>(
        `/api/v1/projects/${repoId}/learnings`,
        {
          method: "POST",
          body: JSON.stringify({
            type: data.type,
            description: data.description,
            details: data.details || "",
            scope: data.scope || "",
            confidence: data.confidence ?? 0.7,
          }),
        },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["learnings", "list", repoId] });
    },
  });
}

export function useLearningFeedback(repoId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { learningId: number; helpful: boolean }) =>
      apiFetch<LearningTextResult>(
        `/api/v1/projects/${repoId}/learnings/${data.learningId}/feedback`,
        {
          method: "POST",
          body: JSON.stringify({ helpful: data.helpful }),
        },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["learnings", "list", repoId] });
    },
  });
}
