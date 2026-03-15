import { useState } from "react";
import { useParams, useNavigate } from "react-router";
import { useBranchCompare } from "@/api/hooks/useGit";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { EmptyState } from "@/components/shared/EmptyState";
import { ROUTES } from "@/lib/routes";
import {
  GitCompare,
  Plus,
  Minus,
  FileEdit,
  FilePlus,
  FileX,
} from "lucide-react";

function statusIcon(status: string) {
  switch (status) {
    case "added":
      return <FilePlus className="h-4 w-4 text-green-400" />;
    case "deleted":
    case "removed":
      return <FileX className="h-4 w-4 text-red-400" />;
    default:
      return <FileEdit className="h-4 w-4 text-amber-400" />;
  }
}

function statusBadgeVariant(status: string): "success" | "destructive" | "warning" {
  switch (status) {
    case "added":
      return "success";
    case "deleted":
    case "removed":
      return "destructive";
    default:
      return "warning";
  }
}

export function BranchComparePage() {
  const { orgId, repoId } = useParams();
  const navigate = useNavigate();

  const [base, setBase] = useState("");
  const [head, setHead] = useState("");
  const [compareBase, setCompareBase] = useState("");
  const [compareHead, setCompareHead] = useState("");

  const compare = useBranchCompare(orgId!, repoId!, compareBase, compareHead);

  const handleCompare = () => {
    if (!base.trim() || !head.trim()) return;
    setCompareBase(base.trim());
    setCompareHead(head.trim());
  };

  const handleFileClick = (path: string) => {
    navigate(
      `${ROUTES.FILES(orgId!, repoId!)}?path=${encodeURIComponent(path)}`,
    );
  };

  const totalAdditions = compare.data?.files.reduce((s, f) => s + f.additions, 0) ?? 0;
  const totalDeletions = compare.data?.files.reduce((s, f) => s + f.deletions, 0) ?? 0;

  return (
    <div className="space-y-6 max-w-4xl">
      {/* Header */}
      <div className="flex items-center gap-3">
        <GitCompare className="h-5 w-5 text-muted-foreground" />
        <h2 className="text-xl font-semibold">Branch Compare</h2>
      </div>

      {/* Branch inputs */}
      <Card>
        <CardContent className="pt-6">
          <div className="flex items-end gap-3">
            <div className="flex-1">
              <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                Base branch
              </label>
              <Input
                placeholder="e.g. main"
                value={base}
                onChange={(e) => setBase(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleCompare()}
              />
            </div>
            <span className="pb-2 text-muted-foreground text-sm">...</span>
            <div className="flex-1">
              <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                Head branch
              </label>
              <Input
                placeholder="e.g. feature/my-branch"
                value={head}
                onChange={(e) => setHead(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleCompare()}
              />
            </div>
            <Button
              onClick={handleCompare}
              disabled={compare.isLoading || !base.trim() || !head.trim()}
            >
              {compare.isLoading ? "Comparing..." : "Compare"}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Loading */}
      {compare.isLoading && <LoadingSpinner />}

      {/* Results */}
      {compare.data && compare.data.files.length > 0 && (
        <div className="space-y-3">
          {/* Summary */}
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">
              Comparing{" "}
              <code className="rounded bg-muted px-1.5 py-0.5 text-xs font-mono">
                {compare.data.from_ref}
              </code>
              {" "}&rarr;{" "}
              <code className="rounded bg-muted px-1.5 py-0.5 text-xs font-mono">
                {compare.data.to_ref}
              </code>
            </span>
            <div className="flex items-center gap-3">
              <span className="text-muted-foreground">
                {compare.data.files.length} file{compare.data.files.length !== 1 ? "s" : ""} changed
              </span>
              <span className="flex items-center gap-1 text-green-400">
                <Plus className="h-3 w-3" />
                {totalAdditions}
              </span>
              <span className="flex items-center gap-1 text-red-400">
                <Minus className="h-3 w-3" />
                {totalDeletions}
              </span>
            </div>
          </div>

          {/* File list */}
          <Card>
            <CardContent className="p-0">
              <div className="divide-y divide-border">
                {compare.data.files.map((file) => (
                  <button
                    key={file.path}
                    onClick={() => handleFileClick(file.path)}
                    className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-primary/[0.04] transition-colors"
                  >
                    {statusIcon(file.status)}
                    <span className="flex-1 truncate text-sm font-mono">
                      {file.old_path && file.old_path !== file.path ? (
                        <>
                          <span className="text-muted-foreground line-through">
                            {file.old_path}
                          </span>
                          {" "}&rarr; {file.path}
                        </>
                      ) : (
                        file.path
                      )}
                    </span>
                    <Badge variant={statusBadgeVariant(file.status)}>
                      {file.status}
                    </Badge>
                    <div className="flex items-center gap-2 text-xs shrink-0 w-24 justify-end">
                      {file.additions > 0 && (
                        <span className="text-green-400">+{file.additions}</span>
                      )}
                      {file.deletions > 0 && (
                        <span className="text-red-400">-{file.deletions}</span>
                      )}
                    </div>
                  </button>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* No changes */}
      {compare.data && compare.data.files.length === 0 && (
        <EmptyState
          icon={<GitCompare className="h-12 w-12" />}
          title="No differences"
          description={`No file changes between ${compare.data.from_ref} and ${compare.data.to_ref}`}
        />
      )}

      {/* Initial state */}
      {!compare.data && !compare.isLoading && (
        <EmptyState
          icon={<GitCompare className="h-12 w-12" />}
          title="Compare branches"
          description="Enter two branch names or commit SHAs to see what changed between them"
        />
      )}
    </div>
  );
}
