import { useNavigate } from "react-router";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { X } from "lucide-react";
import type { SimilarFileResult } from "@/api/hooks/useEmbeddings";

const EXT_COLORS: Record<string, string> = {
  py: "#3572A5",
  ts: "#3178c6",
  tsx: "#3178c6",
  js: "#f1e05a",
  jsx: "#f1e05a",
  go: "#00ADD8",
  rs: "#dea584",
  java: "#b07219",
  rb: "#701516",
  css: "#563d7c",
  html: "#e34c26",
};

function getExtColor(path: string): string {
  const ext = path.split(".").pop()?.toLowerCase() || "";
  return EXT_COLORS[ext] || "#6366f1";
}

interface SimilarFilesPanelProps {
  sourceFile: string;
  results: SimilarFileResult[];
  onClose: () => void;
}

export function SimilarFilesPanel({ sourceFile, results, onClose }: SimilarFilesPanelProps) {
  const navigate = useNavigate();

  return (
    <Card>
      <CardHeader className="pb-2 flex flex-row items-center justify-between">
        <CardTitle className="text-sm">
          Files similar to <code className="text-xs bg-muted px-1 py-0.5 rounded">{sourceFile}</code>
        </CardTitle>
        <Button variant="ghost" size="sm" onClick={onClose}>
          <X className="h-4 w-4" />
        </Button>
      </CardHeader>
      <CardContent className="space-y-1">
        {results.length === 0 ? (
          <p className="text-sm text-muted-foreground">No similar files found.</p>
        ) : (
          results.map((r, i) => {
            const pct = (r.score * 100).toFixed(0);
            return (
              <button
                key={i}
                onClick={() => navigate(`../files?path=${encodeURIComponent(r.file_path)}`)}
                className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-accent/30 transition-colors"
              >
                <span
                  className="inline-block h-2.5 w-2.5 rounded-full shrink-0"
                  style={{ backgroundColor: getExtColor(r.file_path) }}
                />
                <span className="font-mono text-xs text-primary truncate flex-1">{r.file_path}</span>
                <div className="flex items-center gap-1.5 shrink-0">
                  <div className="h-1.5 w-16 rounded-full bg-muted overflow-hidden">
                    <div
                      className="h-full rounded-full bg-violet-500"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <span className="text-xs text-muted-foreground w-8 text-right">{pct}%</span>
                </div>
              </button>
            );
          })
        )}
      </CardContent>
    </Card>
  );
}
