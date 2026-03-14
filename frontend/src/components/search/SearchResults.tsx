import { useNavigate } from "react-router";
import type { SearchResult } from "@/api/generated/schema";
import { FileText } from "lucide-react";

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

function highlightSnippet(text: string, query: string) {
  if (!query.trim()) return <>{text}</>;
  const words = query
    .split(/\s+/)
    .filter((w) => w.length >= 2)
    .map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (!words.length) return <>{text}</>;

  const pattern = new RegExp(`(${words.join("|")})`, "gi");
  const parts = text.split(pattern);

  return (
    <>
      {parts.map((part, i) =>
        pattern.test(part) ? (
          <mark
            key={i}
            className="bg-yellow-500/30 text-yellow-200 rounded-sm px-0.5"
          >
            {part}
          </mark>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  );
}

interface SearchResultsProps {
  results: SearchResult[];
  repoId: string;
  query?: string;
}

export function SearchResults({ results, query = "" }: SearchResultsProps) {
  const navigate = useNavigate();

  const handleClick = (result: SearchResult) => {
    const path = encodeURIComponent(result.file);
    const hash = result.line ? `#L${result.line}` : "";
    navigate(`../files?path=${path}${hash}`);
  };

  return (
    <div className="divide-y divide-border rounded-lg border border-border">
      {results.map((result, i) => (
        <button
          key={i}
          onClick={() => handleClick(result)}
          className="flex w-full flex-col gap-1 px-4 py-3 text-left hover:bg-accent/30 transition-colors"
        >
          <div className="flex items-center gap-2 text-sm">
            <span
              className="inline-block h-2.5 w-2.5 rounded-full shrink-0"
              style={{ backgroundColor: getExtColor(result.file) }}
            />
            <FileText className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
            <span className="font-mono text-primary truncate">
              {result.file}
            </span>
            {result.line > 0 && (
              <span className="text-xs font-mono text-blue-400 shrink-0">
                :{result.line}
              </span>
            )}
            <span className="ml-auto text-xs text-muted-foreground shrink-0">
              {(result.score * 100).toFixed(0)}% match
            </span>
          </div>
          {result.content && (
            <code className="block overflow-x-auto text-xs text-muted-foreground font-mono whitespace-pre-wrap pl-[1.375rem]">
              {highlightSnippet(result.content, query)}
            </code>
          )}
        </button>
      ))}
    </div>
  );
}
