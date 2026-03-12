import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type {
  CommitInfo,
  CommitDetail,
  FileDiff,
  BlameEntry,
} from "@/api/generated/schema";

export function useCommitLog(
  orgId: string,
  repoId: string,
  opts: { limit?: number; offset?: number; branch?: string } = {},
) {
  return useQuery({
    queryKey: ["git", "commits", orgId, repoId, opts],
    queryFn: () => {
      const params = new URLSearchParams();
      if (opts.limit) params.set("limit", String(opts.limit));
      if (opts.offset) params.set("offset", String(opts.offset));
      if (opts.branch) params.set("branch", opts.branch);
      return apiFetch<{ commits: CommitInfo[]; total: number }>(
        `/api/v2/projects/${repoId}/commits?${params}`,
      );
    },
    enabled: !!repoId,
  });
}

export function useCommitDetail(
  orgId: string,
  repoId: string,
  sha: string,
) {
  return useQuery({
    queryKey: ["git", "commit", orgId, repoId, sha],
    queryFn: () =>
      apiFetch<CommitDetail>(`/api/v2/projects/${repoId}/commits/${sha}`),
    enabled: !!repoId && !!sha,
  });
}

export function useDiff(
  orgId: string,
  repoId: string,
  from: string,
  to: string,
) {
  return useQuery({
    queryKey: ["git", "diff", orgId, repoId, from, to],
    queryFn: () => {
      const params = new URLSearchParams({ from, to });
      return apiFetch<{ files: FileDiff[] }>(
        `/api/v2/projects/${repoId}/diff?${params}`,
      );
    },
    enabled: !!repoId && !!from && !!to,
  });
}

export function useBlame(orgId: string, repoId: string, path: string) {
  return useQuery({
    queryKey: ["git", "blame", orgId, repoId, path],
    queryFn: () =>
      apiFetch<{ entries: BlameEntry[] }>(
        `/api/v2/projects/${repoId}/blame/${path}`,
      ),
    enabled: !!repoId && !!path,
  });
}
