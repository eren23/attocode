import { LoginForm } from "@/components/auth/LoginForm";
import { GitHubButton } from "@/components/auth/GitHubButton";
import { GoogleButton } from "@/components/auth/GoogleButton";
import { useProviders } from "@/api/hooks/useAuth";
import { Code2 } from "lucide-react";

export function LoginPage() {
  const { data: providerData } = useProviders();
  const providers = providerData?.providers ?? ["email"];
  const hasEmail = providers.includes("email");
  const hasGithub = providers.includes("github");
  const hasGoogle = providers.includes("google");
  const hasOAuth = hasGithub || hasGoogle;

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="w-full max-w-sm space-y-6 rounded-lg border border-border bg-card p-8">
        <div className="flex flex-col items-center gap-2">
          <Code2 className="h-8 w-8 text-primary" />
          <h1 className="text-xl font-semibold">Sign in to Attocode</h1>
          <p className="text-sm text-muted-foreground">
            Code Intelligence Dashboard
          </p>
        </div>
        {hasEmail && <LoginForm />}
        {hasEmail && hasOAuth && (
          <div className="relative">
            <div className="absolute inset-0 flex items-center">
              <span className="w-full border-t border-border" />
            </div>
            <div className="relative flex justify-center text-xs uppercase">
              <span className="bg-card px-2 text-muted-foreground">or</span>
            </div>
          </div>
        )}
        {hasGithub && <GitHubButton />}
        {hasGoogle && <GoogleButton />}
      </div>
    </div>
  );
}
