import createClient, { type Middleware } from "openapi-fetch";
import { getAccessToken, silentRefresh, clearTokens } from "@/lib/auth";

const authMiddleware: Middleware = {
  async onRequest({ request }) {
    const token = getAccessToken();
    if (token) {
      request.headers.set("Authorization", `Bearer ${token}`);
    }
    return request;
  },
  async onResponse({ response, request }) {
    if (response.status === 401 && !request.url.includes("/auth/refresh")) {
      const refreshed = await silentRefresh();
      if (refreshed) {
        // Retry with new token
        const newToken = getAccessToken();
        const retryReq = new Request(request, {
          headers: new Headers(request.headers),
        });
        if (newToken) {
          retryReq.headers.set("Authorization", `Bearer ${newToken}`);
        }
        return fetch(retryReq);
      } else {
        clearTokens();
        window.location.href = "/login";
      }
    }
    return response;
  },
};

export const api = createClient({ baseUrl: "" });
api.use(authMiddleware);

// Typed fetch helper for endpoints not in the generated schema
export async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const token = getAccessToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(path, { ...options, headers });

  if (res.status === 401 && !path.includes("/auth/refresh")) {
    const refreshed = await silentRefresh();
    if (refreshed) {
      headers["Authorization"] = `Bearer ${getAccessToken()}`;
      const retry = await fetch(path, { ...options, headers });
      if (!retry.ok) throw new ApiError(retry.status, await retry.text());
      return retry.json() as Promise<T>;
    }
    clearTokens();
    window.location.href = "/login";
  }

  if (!res.ok) {
    throw new ApiError(res.status, await res.text());
  }

  return res.json() as Promise<T>;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public body: string,
  ) {
    super(`API Error ${status}: ${body}`);
    this.name = "ApiError";
  }

  get detail(): string {
    try {
      return (JSON.parse(this.body) as { detail?: string }).detail ?? this.body;
    } catch {
      return this.body;
    }
  }
}
