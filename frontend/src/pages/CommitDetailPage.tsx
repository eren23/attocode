import { useParams } from "react-router";
import { useCommitDetail } from "@/api/hooks/useGit";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { CommitDetail } from "@/components/git/CommitDetail";
import { DiffViewer } from "@/components/git/DiffViewer";

export function CommitDetailPage() {
  const { orgId, repoId, sha } = useParams();
  const { data: commit, isLoading } = useCommitDetail(orgId!, repoId!, sha!);

  if (isLoading) return <LoadingSpinner />;
  if (!commit) return <p className="text-muted-foreground">Commit not found</p>;

  return (
    <div className="space-y-6">
      <CommitDetail commit={commit} />
      <DiffViewer repoId={repoId!} orgId={orgId!} fromSha={commit.parents[0] ?? ""} toSha={sha!} />
    </div>
  );
}
