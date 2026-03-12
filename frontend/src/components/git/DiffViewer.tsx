import { useDiff } from "@/api/hooks/useGit";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { cn } from "@/lib/cn";

interface DiffViewerProps {
  orgId: string;
  repoId: string;
  fromSha: string;
  toSha: string;
}

export function DiffViewer({ orgId, repoId, fromSha, toSha }: DiffViewerProps) {
  const { data, isLoading } = useDiff(orgId, repoId, fromSha, toSha);

  if (isLoading) return <LoadingSpinner />;
  if (!data?.files?.length) {
    return <p className="text-sm text-muted-foreground">No diff available</p>;
  }

  return (
    <div className="space-y-4">
      {data.files.map((file) => (
        <div
          key={file.path}
          className="rounded-lg border border-border overflow-hidden"
        >
          <div className="flex items-center justify-between bg-zinc-900 px-4 py-2 text-sm">
            <span className="font-mono">{file.path}</span>
            <span className="text-xs text-muted-foreground">{file.status}</span>
          </div>
          <div className="overflow-x-auto">
            {file.hunks.map((hunk, hi) => (
              <div key={hi}>
                <div className="bg-zinc-800/50 px-4 py-1 text-xs text-muted-foreground font-mono">
                  {hunk.header}
                </div>
                {hunk.lines.map((line, li) => (
                  <div
                    key={li}
                    className={cn(
                      "px-4 py-0 text-xs font-mono whitespace-pre",
                      line.type === "add" &&
                        "bg-emerald-500/10 text-emerald-300",
                      line.type === "delete" && "bg-red-500/10 text-red-300",
                      line.type === "context" && "text-muted-foreground",
                    )}
                  >
                    <span className="inline-block w-4 select-none text-right opacity-50">
                      {line.type === "add"
                        ? "+"
                        : line.type === "delete"
                          ? "-"
                          : " "}
                    </span>
                    {line.content}
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
