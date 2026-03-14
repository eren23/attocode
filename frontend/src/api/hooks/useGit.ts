import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type {
  CommitInfo,
  CommitDetail,
  FileDiff,
  BlameEntry,
} from "@/api/generated/schema";

// Backend commit shape differs from frontend — map fields
interface BackendCommit {
  oid: string;
  message: string;
  author_name: string;
  author_email: string;
  timestamp: number;
  parent_oids: string[];
}

function mapCommit(c: BackendCommit): CommitInfo {
  return {
    sha: c.oid,
    message: c.message,
    author_name: c.author_name,
    author_email: c.author_email,
    authored_at: new Date(c.timestamp * 1000).toISOString(),
    parents: c.parent_oids,
  };
}

export function useCommitLog(
  orgId: string,
  repoId: string,
  opts: { limit?: number; offset?: number; branch?: string } = {},
) {
  return useQuery({
    queryKey: ["git", "commits", orgId, repoId, opts],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (opts.limit) params.set("limit", String(opts.limit));
      if (opts.offset) params.set("offset", String(opts.offset));
      if (opts.branch) params.set("branch", opts.branch);
      const res = await apiFetch<{
        commits: BackendCommit[];
        total: number;
        has_more: boolean;
      }>(`/api/v2/projects/${repoId}/commits?${params}`);
      return {
        commits: res.commits.map(mapCommit),
        total: res.total,
      };
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
    queryFn: async () => {
      const res = await apiFetch<{
        commit: BackendCommit;
        files: {
          path: string;
          status: string;
          additions: number;
          deletions: number;
        }[];
      }>(`/api/v2/projects/${repoId}/commits/${sha}`);
      return {
        ...mapCommit(res.commit),
        files_changed: res.files.map((f) => ({
          path: f.path,
          status: f.status,
          additions: f.additions,
          deletions: f.deletions,
        })),
      } as CommitDetail;
    },
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

interface BackendBlameHunk {
  commit_oid: string;
  author_name: string;
  author_email: string;
  timestamp: number;
  start_line: number;
  end_line: number;
}

export function useBlame(orgId: string, repoId: string, path: string) {
  return useQuery({
    queryKey: ["git", "blame", orgId, repoId, path],
    queryFn: async () => {
      const hunks = await apiFetch<BackendBlameHunk[]>(
        `/api/v2/projects/${repoId}/blame/${encodeURIComponent(path)}`,
      );
      return {
        entries: hunks.map(
          (h): BlameEntry => ({
            sha: h.commit_oid,
            author: h.author_name,
            date: new Date(h.timestamp * 1000).toISOString(),
            line_start: h.start_line,
            line_end: h.end_line,
          }),
        ),
      };
    },
    enabled: !!repoId && !!path,
  });
}

export function useBranchCompare(
  orgId: string,
  repoId: string,
  base: string,
  head: string,
) {
  return useQuery({
    queryKey: ["git", "branch-compare", orgId, repoId, base, head],
    queryFn: () => {
      const params = new URLSearchParams({ from: base, to: head });
      return apiFetch<{
        from_ref: string;
        to_ref: string;
        files: {
          path: string;
          status: string;
          old_path: string | null;
          additions: number;
          deletions: number;
        }[];
      }>(`/api/v2/projects/${repoId}/diff?${params}`);
    },
    enabled: !!repoId && !!base && !!head && base !== head,
  });
}
