import { Link, useLocation, useParams } from "react-router";
import {
  Code2,
  FolderGit2,
  GitCommitHorizontal,
  Search,
  BarChart3,
  Network,
  Database,
  Activity,
  Settings,
  Home,
} from "lucide-react";
import { cn } from "@/lib/cn";
import { ROUTES } from "@/lib/routes";

const NAV_ITEMS = [
  { label: "Dashboard", icon: Home, href: "/" },
];

function getRepoNav(orgId: string, repoId: string) {
  return [
    { label: "Files", icon: FolderGit2, href: ROUTES.FILES(orgId, repoId) },
    {
      label: "Commits",
      icon: GitCommitHorizontal,
      href: ROUTES.COMMITS(orgId, repoId),
    },
    { label: "Search", icon: Search, href: ROUTES.SEARCH(orgId, repoId) },
    {
      label: "Analysis",
      icon: BarChart3,
      href: ROUTES.ANALYSIS(orgId, repoId),
    },
    { label: "Graph", icon: Network, href: ROUTES.GRAPH(orgId, repoId) },
    {
      label: "Embeddings",
      icon: Database,
      href: ROUTES.EMBEDDINGS(orgId, repoId),
    },
  ];
}

function getOrgNav(orgId: string) {
  return [
    { label: "Activity", icon: Activity, href: ROUTES.ACTIVITY(orgId) },
    { label: "Settings", icon: Settings, href: ROUTES.SETTINGS(orgId) },
  ];
}

export function Sidebar() {
  const location = useLocation();
  const { orgId, repoId } = useParams();

  return (
    <aside className="flex h-full w-56 flex-col border-r border-border bg-zinc-950">
      <div className="flex h-14 items-center gap-2 border-b border-border px-4">
        <Code2 className="h-5 w-5 text-primary" />
        <span className="font-semibold text-sm">Attocode</span>
      </div>

      <nav className="flex-1 overflow-y-auto p-2">
        <div className="space-y-1">
          {NAV_ITEMS.map((item) => (
            <Link
              key={item.href}
              to={item.href}
              className={cn(
                "flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors",
                location.pathname === item.href
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
              )}
            >
              <item.icon className="h-4 w-4" />
              {item.label}
            </Link>
          ))}
        </div>

        {orgId && repoId && (
          <>
            <div className="mt-6 mb-2 px-3">
              <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                Repository
              </span>
            </div>
            <div className="space-y-1">
              {getRepoNav(orgId, repoId).map((item) => (
                <Link
                  key={item.href}
                  to={item.href}
                  className={cn(
                    "flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors",
                    location.pathname.startsWith(item.href)
                      ? "bg-accent text-accent-foreground"
                      : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
                  )}
                >
                  <item.icon className="h-4 w-4" />
                  {item.label}
                </Link>
              ))}
            </div>
          </>
        )}

        {orgId && (
          <>
            <div className="mt-6 mb-2 px-3">
              <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                Organization
              </span>
            </div>
            <div className="space-y-1">
              {getOrgNav(orgId).map((item) => (
                <Link
                  key={item.href}
                  to={item.href}
                  className={cn(
                    "flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors",
                    location.pathname.startsWith(item.href)
                      ? "bg-accent text-accent-foreground"
                      : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
                  )}
                >
                  <item.icon className="h-4 w-4" />
                  {item.label}
                </Link>
              ))}
            </div>
          </>
        )}
      </nav>
    </aside>
  );
}
