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
  Shield,
  BookOpen,
  GitCompare,
} from "lucide-react";
import { cn } from "@/lib/cn";
import { ROUTES } from "@/lib/routes";

const NAV_ITEMS = [
  { label: "Dashboard", icon: Home, href: "/" },
];

const CORE_REPO_NAV = ["Files", "Commits", "Search"];

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
      label: "Security",
      icon: Shield,
      href: ROUTES.SECURITY(orgId, repoId),
    },
    {
      label: "Embeddings",
      icon: Database,
      href: ROUTES.EMBEDDINGS(orgId, repoId),
    },
    {
      label: "Knowledge Base",
      icon: BookOpen,
      href: ROUTES.LEARNINGS(orgId, repoId),
    },
    {
      label: "Compare",
      icon: GitCompare,
      href: ROUTES.BRANCH_COMPARE(orgId, repoId),
    },
  ];
}

function getOrgNav(orgId: string) {
  return [
    { label: "Activity", icon: Activity, href: ROUTES.ACTIVITY(orgId) },
    { label: "Settings", icon: Settings, href: ROUTES.SETTINGS(orgId) },
  ];
}

function SectionDivider({ label }: { label: string }) {
  return (
    <div className="mt-6 mb-2 flex items-center gap-2 px-3">
      <div className="h-px flex-1 bg-border/40" />
      <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </span>
      <div className="h-px flex-1 bg-border/40" />
    </div>
  );
}

function NavLink({
  item,
  isActive,
}: {
  item: { label: string; icon: React.ComponentType<{ className?: string }>; href: string };
  isActive: boolean;
}) {
  return (
    <Link
      to={item.href}
      aria-current={isActive ? "page" : undefined}
      className={cn(
        "flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors",
        isActive
          ? "border-l-2 border-primary bg-primary/[0.08] text-foreground"
          : "text-muted-foreground hover:bg-white/[0.04] hover:text-foreground",
      )}
    >
      <item.icon
        className={cn("h-4 w-4", isActive && "text-primary")}
      />
      {item.label}
    </Link>
  );
}

export function Sidebar() {
  const location = useLocation();
  const { orgId, repoId } = useParams();

  const repoNav = orgId && repoId ? getRepoNav(orgId, repoId) : [];
  const coreNav = repoNav.filter((i) => CORE_REPO_NAV.includes(i.label));
  const insightNav = repoNav.filter((i) => !CORE_REPO_NAV.includes(i.label));

  return (
    <aside className="flex h-full w-60 flex-col border-r border-border bg-[--color-surface-1]">
      <div className="flex h-16 items-center gap-2.5 border-b border-border px-4">
        <div className="flex items-center justify-center rounded-lg bg-primary/10 p-1.5 ring-1 ring-primary/20">
          <Code2 className="h-5 w-5 text-primary" />
        </div>
        <div className="flex flex-col">
          <span className="font-semibold text-sm">Attocode</span>
          <span className="text-[10px] text-muted-foreground">Code Intelligence</span>
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto p-2">
        <div className="space-y-1">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.href}
              item={item}
              isActive={location.pathname === item.href}
            />
          ))}
        </div>

        {orgId && repoId && (
          <>
            <SectionDivider label="Code" />
            <div className="space-y-1">
              {coreNav.map((item) => (
                <NavLink
                  key={item.href}
                  item={item}
                  isActive={location.pathname.startsWith(item.href)}
                />
              ))}
            </div>
            <SectionDivider label="Insights" />
            <div className="space-y-1">
              {insightNav.map((item) => (
                <NavLink
                  key={item.href}
                  item={item}
                  isActive={location.pathname.startsWith(item.href)}
                />
              ))}
            </div>
          </>
        )}

        {orgId && (
          <>
            <SectionDivider label="Organization" />
            <div className="space-y-1">
              {getOrgNav(orgId).map((item) => (
                <NavLink
                  key={item.href}
                  item={item}
                  isActive={location.pathname.startsWith(item.href)}
                />
              ))}
            </div>
          </>
        )}
      </nav>
    </aside>
  );
}
