import type { ConventionEntry } from "@/api/generated/schema";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/shared/EmptyState";
import { BookOpen } from "lucide-react";

export function ConventionsPanel({
  conventions,
}: {
  conventions: ConventionEntry[];
}) {
  if (!conventions.length) {
    return (
      <EmptyState
        icon={<BookOpen className="h-8 w-8" />}
        title="No conventions detected"
      />
    );
  }

  return (
    <div className="grid gap-4 md:grid-cols-2">
      {conventions.map((conv, i) => (
        <Card key={i}>
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm">{conv.category}</CardTitle>
              <Badge variant="outline">
                {(conv.confidence * 100).toFixed(0)}%
              </Badge>
            </div>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground mb-2">{conv.pattern}</p>
            {conv.examples.length > 0 && (
              <div className="space-y-1">
                <p className="text-xs font-medium text-muted-foreground">
                  Examples:
                </p>
                {conv.examples.slice(0, 3).map((ex, j) => (
                  <code
                    key={j}
                    className="block truncate text-xs text-primary/80 font-mono"
                  >
                    {ex}
                  </code>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
