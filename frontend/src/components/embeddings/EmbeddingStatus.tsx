import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { EmbeddingStatus } from "@/api/generated/schema";

export function EmbeddingCoverageInline({ status }: { status: EmbeddingStatus }) {
  const pct = status.total_files
    ? ((status.embedded_files / status.total_files) * 100).toFixed(1)
    : "0";

  return (
    <div className="flex items-center gap-3">
      {/* Mini donut */}
      <svg width="32" height="32" viewBox="0 0 32 32">
        <circle cx="16" cy="16" r="12" fill="none" stroke="#27272a" strokeWidth="4" />
        <circle
          cx="16" cy="16" r="12"
          fill="none" stroke="#8b5cf6" strokeWidth="4"
          strokeDasharray={`${status.coverage * 75.4} 75.4`}
          strokeLinecap="round"
          transform="rotate(-90 16 16)"
        />
      </svg>
      <span className="text-sm text-muted-foreground">
        {status.total_files.toLocaleString()} files · {pct}% coverage
      </span>
    </div>
  );
}

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
        {status.provider_available === false && (
          <div className="mb-4 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
            <strong>No embedding provider configured.</strong>{" "}
            {status.provider_hint || "Install sentence-transformers or set OPENAI_API_KEY."}
          </div>
        )}
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
              strokeDasharray={`${status.coverage * 201} 201`}
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
