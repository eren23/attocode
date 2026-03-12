import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { PresenceEntry } from "@/api/generated/schema";

export function usePresence(repoId: string) {
  return useQuery({
    queryKey: ["presence", repoId],
    queryFn: () =>
      apiFetch<{ users: PresenceEntry[] }>(
        `/api/v1/repos/${repoId}/presence`,
      ),
    enabled: !!repoId,
    refetchInterval: 15000,
  });
}
