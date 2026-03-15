import { useLocation, useParams } from "react-router";
import { useMe, useLogout } from "@/api/hooks/useAuth";
import { Button } from "@/components/ui/button";
import { LogOut, User } from "lucide-react";

function useBreadcrumb() {
  const { pathname } = useLocation();
  const { orgId, repoId } = useParams();

  if (orgId && repoId) {
    const segments = pathname.split("/").filter(Boolean);
    // /org/:orgId/repo/:repoId/:page
    const page = segments[4] || "files";
    const pageLabel = page.charAt(0).toUpperCase() + page.slice(1).replace(/-/g, " ");
    return { org: orgId, repo: repoId, page: pageLabel };
  }

  if (pathname === "/") return { page: "Dashboard" };
  const segment = pathname.slice(1).split("/")[0] || "home";
  return { page: segment.charAt(0).toUpperCase() + segment.slice(1) };
}

export function Topbar() {
  const { data: user } = useMe();
  const logout = useLogout();
  const breadcrumb = useBreadcrumb();

  return (
    <header className="flex h-14 items-center justify-between border-b border-border/30 bg-[--color-surface-1]/80 backdrop-blur-md px-6">
      <div className="flex items-center gap-1.5 text-sm">
        {"org" in breadcrumb && (
          <>
            <span className="text-muted-foreground">{breadcrumb.org}</span>
            <span className="text-muted-foreground/50">/</span>
            <span className="text-muted-foreground">{breadcrumb.repo}</span>
            <span className="text-muted-foreground/50">/</span>
          </>
        )}
        <span className="font-medium text-foreground">{breadcrumb.page}</span>
      </div>
      <div className="flex items-center gap-3">
        {user && (
          <div className="flex items-center gap-2 text-sm">
            {user.avatar_url ? (
              <img
                src={user.avatar_url}
                alt={user.name}
                className="h-7 w-7 rounded-full ring-2 ring-border/40"
              />
            ) : (
              <div className="flex h-7 w-7 items-center justify-center rounded-full bg-primary/20 text-primary ring-2 ring-border/40">
                <User className="h-4 w-4" />
              </div>
            )}
            <span className="text-muted-foreground">{user.name}</span>
          </div>
        )}
        <div className="border-l border-border/30 pl-3 ml-1">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => logout.mutate()}
            title="Sign out"
          >
            <LogOut className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </header>
  );
}
