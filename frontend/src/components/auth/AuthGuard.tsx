import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router";
import { useMe, useProviders } from "@/api/hooks/useAuth";
import { isAuthenticated } from "@/lib/auth";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";

export function AuthGuard({ children }: { children: ReactNode }) {
  const location = useLocation();
  const providers = useProviders();
  const { isLoading, isError } = useMe();

  // No auth configured (providers endpoint doesn't exist) -> open access
  if (providers.isError) return <>{children}</>;

  // Auth is configured but still loading providers
  if (providers.isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <LoadingSpinner />
      </div>
    );
  }

  // Auth is configured — enforce login
  if (!isAuthenticated()) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  // Validate token with /me
  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <LoadingSpinner />
      </div>
    );
  }

  if (isError) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return <>{children}</>;
}
