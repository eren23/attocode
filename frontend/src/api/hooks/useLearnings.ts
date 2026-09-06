import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";

export interface Learning {
  id: number; type: string; description: string; details?: string; scope: string;
  confidence: number; status: string; stale?: boolean; author_id?: string; revision?: string;
  created_at?: string; updated_at?: string; helpful_count?: number; unhelpful_count?: number;
}
async function operation<T>(repoId: string, name: string, args: object): Promise<T> {
  const response = await apiFetch<{ data: T }>(`/api/v2/operations/${name}`, {
    method: "POST", body: JSON.stringify({ ...args, workspace: repoId }),
  });
  return response.data;
}
export function useLearnings(repoId: string, opts?: {status?: string; type?: string; scope?: string}) {
  return useQuery({ queryKey: ["learnings", "list", repoId, opts],
    queryFn: () => operation<Learning[]>(repoId, "list_learnings", opts || {}), enabled: !!repoId });
}
export function useRecallLearnings(repoId: string) {
  return useMutation({ mutationFn: async (query: string) => {
    const results = await operation<Learning[]>(repoId, "recall", { query });
    return {results};
  }});
}
export function useRecordLearning(repoId: string) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (data: {type: string; description: string; details?: string; scope?: string; confidence?: number}) =>
    operation<Learning>(repoId, "record_learning", data),
    onSuccess: () => { qc.invalidateQueries({queryKey: ["learnings", "list", repoId]}); },
  });
}
export function useLearningFeedback(repoId: string) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (data: {learningId: number; helpful: boolean}) =>
    operation<Learning>(repoId, "learning_feedback", {learning_id: data.learningId, helpful: data.helpful}),
    onSuccess: () => { qc.invalidateQueries({queryKey: ["learnings", "list", repoId]}); },
  });
}
export function useUpdateLearning(repoId: string) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (data: {learning_id: number; description?: string; details?: string; status?: string}) =>
    operation<Learning>(repoId, "update_learning", data),
    onSuccess: () => { qc.invalidateQueries({queryKey: ["learnings", "list", repoId]}); },
  });
}
