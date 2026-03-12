import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { EmbeddingStatus } from "@/api/generated/schema";

export function EmbeddingStatusCard({ status }: { status: EmbeddingStatus }) {
  const pct = status.total_files
    ? ((status.embedded_files / status.total_files) * 100).toFixed(1)
    : "0";

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Coverage</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex items-center gap-4">
          {/* Donut chart */}
          <svg width="80" height="80" viewBox="0 0 80 80">
            <circle
              cx="40"
              cy="40"
              r="32"
              fill="none"
              stroke="#27272a"
              strokeWidth="8"
            />
            <circle
              cx="40"
              cy="40"
              r="32"
              fill="none"
              stroke="#8b5cf6"
              strokeWidth="8"
              strokeDasharray={`${(status.coverage / 100) * 201} 201`}
              strokeLinecap="round"
              transform="rotate(-90 40 40)"
            />
            <text
              x="40"
              y="44"
              textAnchor="middle"
              className="fill-foreground text-sm font-semibold"
            >
              {pct}%
            </text>
          </svg>

          <div className="space-y-1 text-sm">
            <p>
              <span className="text-muted-foreground">Total files:</span>{" "}
              {status.total_files}
            </p>
            <p>
              <span className="text-muted-foreground">Embedded:</span>{" "}
              {status.embedded_files}
            </p>
            {status.last_updated && (
              <p className="text-xs text-muted-foreground">
                Last updated: {new Date(status.last_updated).toLocaleString()}
              </p>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
