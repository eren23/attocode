import { useState } from "react";
import { useParams } from "react-router";
import { useCommitLog } from "@/api/hooks/useGit";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { Pagination } from "@/components/shared/Pagination";
import { CommitList } from "@/components/git/CommitList";
import { ROUTES } from "@/lib/routes";

export function CommitHistoryPage() {
  const { orgId, repoId } = useParams();
  const [offset, setOffset] = useState(0);
  const limit = 30;
  const { data, isLoading } = useCommitLog(orgId!, repoId!, { limit, offset });

  if (isLoading) return <LoadingSpinner />;

  return (
    <div className="space-y-4">
      {data?.commits && (
        <>
          <CommitList
            commits={data.commits}
            onSelect={(sha) =>
              (window.location.href = ROUTES.COMMIT_DETAIL(orgId!, repoId!, sha))
            }
          />
          <Pagination
            total={data.total}
            limit={limit}
            offset={offset}
            onPageChange={setOffset}
          />
        </>
      )}
    </div>
  );
}
