import type { SearchResult } from "@/api/generated/schema";
import { FileText } from "lucide-react";

interface SearchResultsProps {
  results: SearchResult[];
}

export function SearchResults({ results }: SearchResultsProps) {
  return (
    <div className="divide-y divide-border rounded-lg border border-border">
      {results.map((result, i) => (
        <div key={i} className="px-4 py-3 hover:bg-accent/30 transition-colors">
          <div className="flex items-center gap-2 text-sm">
            <FileText className="h-3.5 w-3.5 text-muted-foreground" />
            <span className="font-mono text-primary">{result.file}</span>
            <span className="text-muted-foreground">:{result.line}</span>
            <span className="ml-auto text-xs text-muted-foreground">
              {(result.score * 100).toFixed(0)}% match
            </span>
          </div>
          <pre className="mt-1 overflow-x-auto text-xs text-muted-foreground font-mono">
            {result.content}
          </pre>
        </div>
      ))}
    </div>
  );
}
