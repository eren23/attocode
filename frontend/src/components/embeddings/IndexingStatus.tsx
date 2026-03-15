import type { IndexingStatus } from "@/api/generated/schema";
import { Badge } from "@/components/ui/badge";

export function IndexingStatusBar({ status }: { status: IndexingStatus }) {
  return (
    <div className="flex items-center gap-3 rounded-md border border-border bg-card px-4 py-3">
      <Badge
        variant={
          status.status === "completed"
            ? "success"
            : status.status === "running"
              ? "warning"
              : "secondary"
        }
      >
        {status.status}
      </Badge>
      <div className="flex-1">
        <div className="h-2 rounded-full bg-muted">
          <div
            className="h-2 rounded-full bg-primary transition-all"
            style={{ width: `${status.progress}%` }}
          />
        </div>
      </div>
      <span className="text-xs text-muted-foreground">
        {status.files_processed} / {status.files_total} files
      </span>
    </div>
  );
}
