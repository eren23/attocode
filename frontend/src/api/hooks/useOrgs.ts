import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type {
  OrgListResponse,
  OrgResponse,
  RepoListResponse,
  RepoResponse,
  MemberListResponse,
  MemberResponse,
} from "@/api/generated/schema";

export function useOrgs() {
  return useQuery({
    queryKey: ["orgs"],
    queryFn: () => apiFetch<OrgListResponse>("/api/v1/orgs"),
  });
}

export function useOrg(orgId: string) {
  return useQuery({
    queryKey: ["orgs", orgId],
    queryFn: () => apiFetch<OrgResponse>(`/api/v1/orgs/${orgId}`),
    enabled: !!orgId,
  });
}

export function useCreateOrg() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { name: string; slug?: string }) =>
      apiFetch<OrgResponse>("/api/v1/orgs", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["orgs"] }),
  });
}

export function useOrgRepos(orgId: string) {
  return useQuery({
    queryKey: ["orgs", orgId, "repos"],
    queryFn: () =>
      apiFetch<RepoListResponse>(`/api/v1/orgs/${orgId}/repos`),
    enabled: !!orgId,
  });
}

export function useRepo(orgId: string, repoId: string) {
  return useQuery({
    queryKey: ["orgs", orgId, "repos", repoId],
    queryFn: () =>
      apiFetch<RepoResponse>(`/api/v1/orgs/${orgId}/repos/${repoId}`),
    enabled: !!orgId && !!repoId,
  });
}

export function useCreateRepo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      orgId,
      ...data
    }: {
      orgId: string;
      name: string;
      clone_url?: string;
      local_path?: string;
      default_branch?: string;
      language?: string;
    }) =>
      apiFetch<RepoResponse>(`/api/v1/orgs/${orgId}/repos`, {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: (_, vars) =>
      qc.invalidateQueries({ queryKey: ["orgs", vars.orgId, "repos"] }),
  });
}

export function useDeleteRepo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ orgId, repoId }: { orgId: string; repoId: string }) =>
      apiFetch<{ detail: string }>(
        `/api/v1/orgs/${orgId}/repos/${repoId}`,
        { method: "DELETE" },
      ),
    onSuccess: (_, vars) =>
      qc.invalidateQueries({ queryKey: ["orgs", vars.orgId, "repos"] }),
  });
}

export function useOrgMembers(orgId: string) {
  return useQuery({
    queryKey: ["orgs", orgId, "members"],
    queryFn: () =>
      apiFetch<MemberListResponse>(`/api/v1/orgs/${orgId}/members`),
    enabled: !!orgId,
  });
}

export function useInviteMember() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      orgId,
      email,
      role,
    }: {
      orgId: string;
      email: string;
      role: string;
    }) =>
      apiFetch<MemberResponse>(`/api/v1/orgs/${orgId}/members`, {
        method: "POST",
        body: JSON.stringify({ email, role }),
      }),
    onSuccess: (_, vars) =>
      qc.invalidateQueries({ queryKey: ["orgs", vars.orgId, "members"] }),
  });
}

export function useRemoveMember() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      orgId,
      userId,
    }: {
      orgId: string;
      userId: string;
    }) =>
      apiFetch<{ detail: string }>(
        `/api/v1/orgs/${orgId}/members/${userId}`,
        { method: "DELETE" },
      ),
    onSuccess: (_, vars) =>
      qc.invalidateQueries({ queryKey: ["orgs", vars.orgId, "members"] }),
  });
}
