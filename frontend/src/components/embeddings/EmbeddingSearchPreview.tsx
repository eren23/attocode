import { useNavigate } from "react-router";
import type { SearchResult } from "@/api/generated/schema";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ArrowRight } from "lucide-react";

interface EmbeddingSearchPreviewProps {
  results: SearchResult[];
  query: string;
  total: number;
  repoId: string;
}

export function EmbeddingSearchPreview({ results, query, total }: EmbeddingSearchPreviewProps) {
  const navigate = useNavigate();

  if (!results.length) return null;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Search Results</CardTitle>
      </CardHeader>
      <CardContent className="space-y-1">
        {results.slice(0, 5).map((r, i) => (
          <button
            key={i}
            onClick={() => navigate(`../files?path=${encodeURIComponent(r.file)}`)}
            className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-accent/30 transition-colors"
          >
            <span className="font-mono text-xs text-primary truncate flex-1">{r.file}</span>
            <span className="shrink-0 rounded bg-violet-500/20 px-1.5 py-0.5 text-xs font-medium text-violet-300">
              {(r.score * 100).toFixed(0)}%
            </span>
          </button>
        ))}
        {total > 5 && (
          <button
            onClick={() => navigate(`../search?q=${encodeURIComponent(query)}`)}
            className="flex items-center gap-1 pt-1 text-xs text-violet-400 hover:text-violet-300 transition-colors"
          >
            View all {total} results in Search <ArrowRight className="h-3 w-3" />
          </button>
        )}
      </CardContent>
    </Card>
  );
}
