import { formatRelativeTime, shortSha } from "@/lib/format";
import type { CommitInfo } from "@/api/generated/schema";
import { GitCommitHorizontal } from "lucide-react";

interface CommitListProps {
  commits: CommitInfo[];
  onSelect: (sha: string) => void;
}

export function CommitList({ commits, onSelect }: CommitListProps) {
  return (
    <div className="divide-y divide-border rounded-lg border border-border">
      {commits.map((commit) => (
        <button
          key={commit.sha}
          onClick={() => onSelect(commit.sha)}
          className="flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-primary/[0.04] transition-colors"
        >
          <GitCommitHorizontal className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
          <div className="flex-1 min-w-0">
            <p className="truncate text-sm font-medium">
              {commit.message.split("\n")[0]}
            </p>
            <p className="text-xs text-muted-foreground">
              {commit.author_name} committed{" "}
              {formatRelativeTime(commit.authored_at)}
            </p>
          </div>
          <code className="shrink-0 text-xs text-primary font-mono">
            {shortSha(commit.sha)}
          </code>
        </button>
      ))}
    </div>
  );
}
