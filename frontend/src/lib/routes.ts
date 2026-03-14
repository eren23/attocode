export const ROUTES = {
  LOGIN: "/login",
  REGISTER: "/register",
  DASHBOARD: "/",
  ORG: (orgId: string) => `/orgs/${orgId}`,
  REPO: (orgId: string, repoId: string) => `/orgs/${orgId}/repos/${repoId}`,
  FILES: (orgId: string, repoId: string, path = "") =>
    `/orgs/${orgId}/repos/${repoId}/files${path ? `/${path}` : ""}`,
  COMMITS: (orgId: string, repoId: string) =>
    `/orgs/${orgId}/repos/${repoId}/commits`,
  COMMIT_DETAIL: (orgId: string, repoId: string, sha: string) =>
    `/orgs/${orgId}/repos/${repoId}/commits/${sha}`,
  SEARCH: (orgId: string, repoId: string) =>
    `/orgs/${orgId}/repos/${repoId}/search`,
  ANALYSIS: (orgId: string, repoId: string) =>
    `/orgs/${orgId}/repos/${repoId}/analysis`,
  GRAPH: (orgId: string, repoId: string) =>
    `/orgs/${orgId}/repos/${repoId}/graph`,
  EMBEDDINGS: (orgId: string, repoId: string) =>
    `/orgs/${orgId}/repos/${repoId}/embeddings`,
  SECURITY: (orgId: string, repoId: string) =>
    `/orgs/${orgId}/repos/${repoId}/security`,
  LEARNINGS: (orgId: string, repoId: string) =>
    `/orgs/${orgId}/repos/${repoId}/learnings`,
  BRANCH_COMPARE: (orgId: string, repoId: string) =>
    `/orgs/${orgId}/repos/${repoId}/compare`,
  ACTIVITY: (orgId: string) => `/orgs/${orgId}/activity`,
  SETTINGS: (orgId: string) => `/orgs/${orgId}/settings`,
  OAUTH_CALLBACK: "/auth/callback",
  NOT_FOUND: "/404",
} as const;
