import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import { setTokens, clearTokens } from "@/lib/auth";
import type { TokenResponse, UserProfile } from "@/api/generated/schema";

export function useProviders() {
  return useQuery({
    queryKey: ["auth", "providers"],
    queryFn: () =>
      apiFetch<{ providers: string[]; registration_enabled: boolean }>(
        "/api/v1/auth/providers",
      ),
    retry: false,
    staleTime: Infinity,
  });
}

export function useMe() {
  return useQuery({
    queryKey: ["auth", "me"],
    queryFn: () => apiFetch<UserProfile>("/api/v1/auth/me"),
    retry: false,
    staleTime: 5 * 60 * 1000,
  });
}

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { email: string; password: string }) =>
      apiFetch<TokenResponse>("/api/v1/auth/login", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: (data) => {
      setTokens(data.access_token, data.refresh_token);
      qc.invalidateQueries({ queryKey: ["auth", "me"] });
    },
  });
}

export function useRegister() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { email: string; password: string; name: string }) =>
      apiFetch<TokenResponse>("/api/v1/auth/register", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: (data) => {
      setTokens(data.access_token, data.refresh_token);
      qc.invalidateQueries({ queryKey: ["auth", "me"] });
    },
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      clearTokens();
    },
    onSuccess: () => {
      qc.clear();
      window.location.href = "/login";
    },
  });
}

export function useUpdateProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { name?: string; avatar_url?: string }) =>
      apiFetch<UserProfile>("/api/v1/auth/me", {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["auth", "me"] });
    },
  });
}

export function useChangePassword() {
  return useMutation({
    mutationFn: (data: { current_password: string; new_password: string }) =>
      apiFetch<{ detail: string }>("/api/v1/auth/me/password", {
        method: "POST",
        body: JSON.stringify(data),
      }),
  });
}
