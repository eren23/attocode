import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { ActivityListResponse } from "@/api/generated/schema";

export function useOrgActivity(orgId: string, limit = 50) {
  return useQuery({
    queryKey: ["activity", orgId, limit],
    queryFn: () =>
      apiFetch<ActivityListResponse>(
        `/api/v1/orgs/${orgId}/activity?limit=${limit}`,
      ),
    enabled: !!orgId,
    refetchInterval: 30000,
  });
}

export function useRepoActivity(repoId: string, limit = 50) {
  return useQuery({
    queryKey: ["activity", "repo", repoId, limit],
    queryFn: () =>
      apiFetch<ActivityListResponse>(
        `/api/v1/repos/${repoId}/activity?limit=${limit}`,
      ),
    enabled: !!repoId,
    refetchInterval: 30000,
  });
}
