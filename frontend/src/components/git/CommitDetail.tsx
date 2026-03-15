import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatRelativeTime, shortSha } from "@/lib/format";
import type { CommitDetail as CommitDetailType } from "@/api/generated/schema";
import { User, Clock, FileText } from "lucide-react";

export function CommitDetail({ commit }: { commit: CommitDetailType }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{commit.message}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap gap-4 text-sm text-muted-foreground">
          <span className="flex items-center gap-1">
            <User className="h-3.5 w-3.5" />
            {commit.author_name}
          </span>
          <span className="flex items-center gap-1">
            <Clock className="h-3.5 w-3.5" />
            {formatRelativeTime(commit.authored_at)}
          </span>
          <code className="font-mono text-xs text-primary">
            {shortSha(commit.sha)}
          </code>
          {commit.parents.map((p) => (
            <Badge key={p} variant="outline">
              parent: {shortSha(p)}
            </Badge>
          ))}
        </div>

        {commit.files_changed.length > 0 && (
          <div className="space-y-1">
            <p className="flex items-center gap-1 text-sm font-medium">
              <FileText className="h-3.5 w-3.5" />
              {commit.files_changed.length} files changed
            </p>
            <div className="max-h-40 overflow-y-auto text-xs">
              {commit.files_changed.map((f) => (
                <div
                  key={f.path}
                  className="flex items-center justify-between py-0.5"
                >
                  <span className="truncate text-muted-foreground">
                    {f.path}
                  </span>
                  <span>
                    {f.additions > 0 && (
                      <span className="text-emerald-400">+{f.additions}</span>
                    )}
                    {f.deletions > 0 && (
                      <span className="ml-1 text-red-400">-{f.deletions}</span>
                    )}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
