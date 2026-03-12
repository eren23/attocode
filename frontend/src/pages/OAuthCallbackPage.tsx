import { useEffect } from "react";
import { useNavigate } from "react-router";
import { setTokens } from "@/lib/auth";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";

export function OAuthCallbackPage() {
  const navigate = useNavigate();

  useEffect(() => {
    const hash = window.location.hash.substring(1);
    const params = new URLSearchParams(hash);
    const accessToken = params.get("access_token");
    const refreshToken = params.get("refresh_token");

    if (accessToken && refreshToken) {
      setTokens(accessToken, refreshToken);
      navigate("/", { replace: true });
    } else {
      navigate("/login", { replace: true });
    }
  }, [navigate]);

  return (
    <div className="flex h-screen items-center justify-center bg-background">
      <LoadingSpinner />
    </div>
  );
}
