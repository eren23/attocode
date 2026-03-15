import { useNavigate } from "react-router";
import type { SearchResult } from "@/api/generated/schema";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ArrowRight } from "lucide-react";

interface EmbeddingSearchPreviewProps {
  results: SearchResult[];
  query: string;
  total: number;
  repoId: string;
  onFindSimilar?: (filePath: string) => void;
}

export function EmbeddingSearchPreview({ results, query, total, onFindSimilar }: EmbeddingSearchPreviewProps) {
  const navigate = useNavigate();

  if (!results.length) return null;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Search Results</CardTitle>
      </CardHeader>
      <CardContent className="space-y-1">
        {results.slice(0, 5).map((r, i) => (
          <div
            key={i}
            className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-primary/[0.04] transition-colors"
          >
            <button
              onClick={() => navigate(`../files?path=${encodeURIComponent(r.file)}`)}
              className="font-mono text-xs text-primary truncate flex-1 text-left"
            >
              {r.file}
            </button>
            <span className="shrink-0 rounded bg-primary/20 px-1.5 py-0.5 text-xs font-medium text-primary">
              {(r.score * 100).toFixed(0)}%
            </span>
            {onFindSimilar && (
              <button
                onClick={() => onFindSimilar(r.file)}
                className="shrink-0 rounded px-2 py-0.5 text-xs text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
              >
                Find Similar
              </button>
            )}
          </div>
        ))}
        {total > 5 && (
          <button
            onClick={() => navigate(`../search?q=${encodeURIComponent(query)}`)}
            className="flex items-center gap-1 pt-1 text-xs text-primary hover:text-primary/80 transition-colors"
          >
            View all {total} results in Search <ArrowRight className="h-3 w-3" />
          </button>
        )}
      </CardContent>
    </Card>
  );
}
