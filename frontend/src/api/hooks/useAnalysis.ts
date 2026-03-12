import { useQuery, useMutation } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type {
  SymbolInfo,
  HotspotEntry,
  ConventionEntry,
  ImpactResult,
  CommunityInfo,
  SecurityFinding,
  CrossRefResult,
} from "@/api/generated/schema";

export function useSymbols(repoId: string, file?: string) {
  return useQuery({
    queryKey: ["analysis", "symbols", repoId, file],
    queryFn: () => {
      const params = new URLSearchParams();
      if (file) params.set("file", file);
      return apiFetch<{ symbols: SymbolInfo[] }>(
        `/api/v2/projects/${repoId}/symbols?${params}`,
      );
    },
    enabled: !!repoId,
  });
}

export function useHotspots(repoId: string) {
  return useQuery({
    queryKey: ["analysis", "hotspots", repoId],
    queryFn: () =>
      apiFetch<{ hotspots: HotspotEntry[] }>(
        `/api/v2/projects/${repoId}/hotspots`,
      ),
    enabled: !!repoId,
  });
}

export function useConventions(repoId: string) {
  return useQuery({
    queryKey: ["analysis", "conventions", repoId],
    queryFn: () =>
      apiFetch<{ conventions: ConventionEntry[] }>(
        `/api/v2/projects/${repoId}/conventions`,
      ),
    enabled: !!repoId,
  });
}

export function useImpactAnalysis(repoId: string) {
  return useMutation({
    mutationFn: (file: string) =>
      apiFetch<ImpactResult>(`/api/v2/projects/${repoId}/impact`, {
        method: "POST",
        body: JSON.stringify({ file }),
      }),
  });
}

export function useCommunities(repoId: string) {
  return useQuery({
    queryKey: ["analysis", "communities", repoId],
    queryFn: () =>
      apiFetch<{ communities: CommunityInfo[] }>(
        `/api/v2/projects/${repoId}/communities`,
      ),
    enabled: !!repoId,
  });
}

export function useSecurityScan(repoId: string) {
  return useMutation({
    mutationFn: (files?: string[]) =>
      apiFetch<{ findings: SecurityFinding[] }>(
        `/api/v2/projects/${repoId}/security-scan`,
        {
          method: "POST",
          body: JSON.stringify({ files }),
        },
      ),
  });
}

export function useCrossRefs(repoId: string, symbol: string) {
  return useQuery({
    queryKey: ["analysis", "cross-refs", repoId, symbol],
    queryFn: () =>
      apiFetch<CrossRefResult>(
        `/api/v2/projects/${repoId}/cross-refs?symbol=${encodeURIComponent(symbol)}`,
      ),
    enabled: !!repoId && !!symbol,
  });
}
