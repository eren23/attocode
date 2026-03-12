import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { UserPreferences } from "@/api/generated/schema";

export function usePreferences() {
  return useQuery({
    queryKey: ["preferences"],
    queryFn: () => apiFetch<UserPreferences>("/api/v1/me/preferences"),
  });
}

export function useUpdatePreferences() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (prefs: Partial<UserPreferences>) =>
      apiFetch<UserPreferences>("/api/v1/me/preferences", {
        method: "PATCH",
        body: JSON.stringify(prefs),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["preferences"] }),
  });
}
