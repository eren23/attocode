import { Outlet, useParams, Link, useLocation } from "react-router";
import { useRepo } from "@/api/hooks/useOrgs";
import { useRepoWebSocket } from "@/api/hooks/useWebSocket";
import { Badge } from "@/components/ui/badge";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { ROUTES } from "@/lib/routes";
import { cn } from "@/lib/cn";
import {
  FolderGit2,
  GitCommitHorizontal,
  Search,
  BarChart3,
  Network,
  Database,
} from "lucide-react";

export function RepoDetailPage() {
  const { orgId, repoId } = useParams();
  const { data: repo, isLoading } = useRepo(orgId!, repoId!);
  useRepoWebSocket(repoId);

  if (isLoading) return <LoadingSpinner />;
  if (!repo) return <p className="text-muted-foreground">Repository not found</p>;

  const tabs = [
    { label: "Files", icon: FolderGit2, href: ROUTES.FILES(orgId!, repoId!) },
    { label: "Commits", icon: GitCommitHorizontal, href: ROUTES.COMMITS(orgId!, repoId!) },
    { label: "Search", icon: Search, href: ROUTES.SEARCH(orgId!, repoId!) },
    { label: "Analysis", icon: BarChart3, href: ROUTES.ANALYSIS(orgId!, repoId!) },
    { label: "Graph", icon: Network, href: ROUTES.GRAPH(orgId!, repoId!) },
    { label: "Embeddings", icon: Database, href: ROUTES.EMBEDDINGS(orgId!, repoId!) },
  ];

  return <RepoTabs repoName={repo.name} indexStatus={repo.index_status} language={repo.language} tabs={tabs} />;
}

function RepoTabs({
  repoName,
  indexStatus,
  language,
  tabs,
}: {
  repoName: string;
  indexStatus: string;
  language: string | null;
  tabs: { label: string; icon: React.ComponentType<{ className?: string }>; href: string }[];
}) {
  const location = useLocation();

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-bold">{repoName}</h1>
        {language && <Badge variant="outline">{language}</Badge>}
        <Badge variant={indexStatus === "indexed" ? "success" : "warning"}>
          {indexStatus}
        </Badge>
      </div>

      <div className="flex gap-1 border-b border-border">
        {tabs.map((tab) => (
          <Link
            key={tab.href}
            to={tab.href}
            className={cn(
              "flex items-center gap-1.5 border-b-2 px-4 py-2 text-sm transition-colors",
              location.pathname.startsWith(tab.href)
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            <tab.icon className="h-4 w-4" />
            {tab.label}
          </Link>
        ))}
      </div>

      <Outlet />
    </div>
  );
}
