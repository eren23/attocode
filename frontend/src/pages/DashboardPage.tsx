import { useState } from "react";
import { Link } from "react-router";
import { useOrgs, useCreateOrg, useOrgRepos, useCreateRepo } from "@/api/hooks/useOrgs";
import { useMe } from "@/api/hooks/useAuth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { EmptyState } from "@/components/shared/EmptyState";
import { ROUTES } from "@/lib/routes";
import { formatRelativeTime } from "@/lib/format";
import {
  Plus,
  FolderGit2,
  Building2,
  GitBranch,
} from "lucide-react";

export function DashboardPage() {
  const { data: user } = useMe();
  const { data: orgsData, isLoading } = useOrgs();
  const [showNewOrg, setShowNewOrg] = useState(false);
  const [newOrgName, setNewOrgName] = useState("");
  const createOrg = useCreateOrg();

  const handleCreateOrg = () => {
    if (!newOrgName.trim()) return;
    createOrg.mutate(
      { name: newOrgName },
      {
        onSuccess: () => {
          setNewOrgName("");
          setShowNewOrg(false);
        },
      },
    );
  };

  if (isLoading) return <LoadingSpinner />;

  return (
    <div className="max-w-5xl space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">
            Welcome back{user?.name ? `, ${user.name}` : ""}
          </h1>
          <p className="text-muted-foreground">
            Your organizations and repositories
          </p>
        </div>
        <Button onClick={() => setShowNewOrg(true)}>
          <Plus className="h-4 w-4" />
          New Organization
        </Button>
      </div>

      {showNewOrg && (
        <Card>
          <CardContent className="flex items-center gap-3 pt-6">
            <Input
              placeholder="Organization name"
              value={newOrgName}
              onChange={(e) => setNewOrgName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleCreateOrg()}
            />
            <Button onClick={handleCreateOrg} disabled={createOrg.isPending}>
              Create
            </Button>
            <Button variant="ghost" onClick={() => setShowNewOrg(false)}>
              Cancel
            </Button>
          </CardContent>
        </Card>
      )}

      {!orgsData?.organizations.length ? (
        <EmptyState
          icon={<Building2 className="h-12 w-12" />}
          title="No organizations yet"
          description="Create your first organization to start analyzing code"
          action={
            <Button onClick={() => setShowNewOrg(true)}>
              <Plus className="h-4 w-4" />
              Create Organization
            </Button>
          }
        />
      ) : (
        <div className="space-y-6">
          {orgsData.organizations.map((org) => (
            <OrgCard key={org.id} orgId={org.id} orgName={org.name} orgPlan={org.plan} />
          ))}
        </div>
      )}
    </div>
  );
}

function OrgCard({
  orgId,
  orgName,
  orgPlan,
}: {
  orgId: string;
  orgName: string;
  orgPlan: string;
}) {
  const { data: repos } = useOrgRepos(orgId);
  const [showNewRepo, setShowNewRepo] = useState(false);
  const [newRepoName, setNewRepoName] = useState("");
  const [newRepoUrl, setNewRepoUrl] = useState("");
  const createRepo = useCreateRepo();

  const handleCreateRepo = () => {
    if (!newRepoName.trim()) return;
    createRepo.mutate(
      {
        orgId,
        name: newRepoName,
        clone_url: newRepoUrl || undefined,
      },
      {
        onSuccess: () => {
          setNewRepoName("");
          setNewRepoUrl("");
          setShowNewRepo(false);
        },
      },
    );
  };

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <div className="flex items-center gap-2">
          <Building2 className="h-4 w-4 text-muted-foreground" />
          <CardTitle className="text-base">
            <Link
              to={ROUTES.ORG(orgId)}
              className="hover:text-primary transition-colors"
            >
              {orgName}
            </Link>
          </CardTitle>
          <Badge variant="secondary">{orgPlan}</Badge>
        </div>
        <Button variant="outline" size="sm" onClick={() => setShowNewRepo(true)}>
          <Plus className="h-3 w-3" />
          Add Repo
        </Button>
      </CardHeader>
      <CardContent>
        {showNewRepo && (
          <div className="mb-4 flex items-center gap-2 rounded-md border border-border p-3">
            <Input
              placeholder="Repository name"
              value={newRepoName}
              onChange={(e) => setNewRepoName(e.target.value)}
              className="flex-1"
            />
            <Input
              placeholder="Clone URL (optional)"
              value={newRepoUrl}
              onChange={(e) => setNewRepoUrl(e.target.value)}
              className="flex-1"
            />
            <Button
              size="sm"
              onClick={handleCreateRepo}
              disabled={createRepo.isPending}
            >
              Add
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowNewRepo(false)}
            >
              Cancel
            </Button>
          </div>
        )}

        {!repos?.repositories.length ? (
          <p className="text-sm text-muted-foreground py-4">
            No repositories yet
          </p>
        ) : (
          <div className="divide-y divide-border">
            {repos.repositories.map((repo) => (
              <Link
                key={repo.id}
                to={ROUTES.REPO(orgId, repo.id)}
                className="flex items-center justify-between py-3 hover:bg-accent/30 -mx-6 px-6 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <FolderGit2 className="h-4 w-4 text-muted-foreground" />
                  <span className="font-medium text-sm">{repo.name}</span>
                  {repo.language && (
                    <Badge variant="outline">{repo.language}</Badge>
                  )}
                </div>
                <div className="flex items-center gap-4 text-xs text-muted-foreground">
                  <span className="flex items-center gap-1">
                    <GitBranch className="h-3 w-3" />
                    {repo.default_branch}
                  </span>
                  <Badge
                    variant={
                      repo.index_status === "indexed" ? "success" : "warning"
                    }
                  >
                    {repo.index_status}
                  </Badge>
                  <span>{formatRelativeTime(repo.created_at)}</span>
                </div>
              </Link>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
