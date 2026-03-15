import { useQuery, useMutation } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type {
  SymbolInfo,
  HotspotsData,
  ConventionsData,
  ImpactResult,
  CommunityResult,
  SecurityScanResult,
  CrossRefResult,
} from "@/api/generated/schema";

// Backend symbol shape differs — map fields
interface BackendSymbol {
  name: string;
  kind: string;
  file_path: string;
  start_line: number;
  end_line: number;
  qualified_name?: string;
  signature?: string;
}

function mapSymbol(s: BackendSymbol): SymbolInfo {
  return {
    name: s.name,
    kind: s.kind,
    file: s.file_path,
    line: s.start_line,
    end_line: s.end_line,
    signature: s.signature || s.qualified_name,
  };
}

export function useSymbols(repoId: string, file?: string) {
  return useQuery({
    queryKey: ["analysis", "symbols", repoId, file],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (file) params.set("path", file);
      const res = await apiFetch<{
        path: string;
        symbols: BackendSymbol[];
      }>(`/api/v2/projects/${repoId}/symbols?${params}`);
      return { symbols: res.symbols.map(mapSymbol) };
    },
    enabled: !!repoId,
  });
}

export function useHotspots(repoId: string) {
  return useQuery({
    queryKey: ["analysis", "hotspots", repoId],
    queryFn: () =>
      apiFetch<HotspotsData>(`/api/v2/projects/${repoId}/hotspots`),
    enabled: !!repoId,
  });
}

export function useConventions(repoId: string, path?: string) {
  return useQuery({
    queryKey: ["analysis", "conventions", repoId, path],
    queryFn: () => {
      const params = new URLSearchParams();
      if (path) params.set("path", path);
      return apiFetch<ConventionsData>(
        `/api/v2/projects/${repoId}/conventions?${params}`,
      );
    },
    enabled: !!repoId,
  });
}

export function useImpactAnalysis(repoId: string) {
  return useMutation({
    mutationFn: (files: string[]) => {
      const params = new URLSearchParams();
      for (const f of files) params.append("files", f);
      return apiFetch<ImpactResult>(
        `/api/v2/projects/${repoId}/impact?${params}`,
      );
    },
  });
}

export function useCommunities(repoId: string) {
  return useQuery({
    queryKey: ["analysis", "communities", repoId],
    queryFn: () =>
      apiFetch<CommunityResult>(
        `/api/v2/projects/${repoId}/graph/communities`,
      ),
    enabled: !!repoId,
  });
}

export function useSecurityScan(repoId: string) {
  return useMutation({
    mutationFn: (opts?: { mode?: string; path?: string }) =>
      apiFetch<SecurityScanResult>(
        `/api/v2/projects/${repoId}/security-scan`,
        {
          method: "POST",
          body: JSON.stringify({ mode: opts?.mode || "quick", path: opts?.path || "" }),
        },
      ),
  });
}

export function useSearchSymbols(repoId: string, query: string, dir?: string) {
  return useQuery({
    queryKey: ["analysis", "search-symbols", repoId, query, dir],
    queryFn: async () => {
      const params = new URLSearchParams({ name: query });
      if (dir) params.set("dir", dir);
      const res = await apiFetch<{ query: string; definitions: BackendSymbol[] }>(
        `/api/v2/projects/${repoId}/search-symbols?${params}`,
      );
      return { query: res.query, definitions: res.definitions.map(mapSymbol) };
    },
    enabled: !!repoId && !!query && query.length >= 2,
    staleTime: 30_000,
  });
}

interface BackendCrossRef {
  symbol: string;
  definitions: { file_path: string; start_line: number; end_line: number; kind: string; name: string; qualified_name: string; signature: string }[];
  references: { ref_kind: string; file_path: string; line: number }[];
  total_references: number;
}

export function useCrossRefs(repoId: string, symbol: string) {
  return useQuery({
    queryKey: ["analysis", "cross-refs", repoId, symbol],
    queryFn: async () => {
      const raw = await apiFetch<BackendCrossRef>(
        `/api/v2/projects/${repoId}/cross-refs?symbol=${encodeURIComponent(symbol)}`,
      );
      return {
        symbol: raw.symbol,
        definitions: raw.definitions.map((d) => ({ file: d.file_path, line: d.start_line })),
        references: raw.references.map((r) => ({ file: r.file_path, line: r.line })),
      } satisfies CrossRefResult;
    },
    enabled: !!repoId && !!symbol,
  });
}
