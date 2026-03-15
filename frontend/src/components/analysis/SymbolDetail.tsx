import { useNavigate } from "react-router";
import type { SymbolInfo } from "@/api/generated/schema";
import { useCrossRefs } from "@/api/hooks/useAnalysis";
import { Loader2, ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";

const KIND_ACCENT: Record<string, string> = {
  function: "border-blue-500/50",
  method: "border-blue-500/50",
  class: "border-amber-500/50",
  interface: "border-purple-500/50",
  type: "border-green-500/50",
  constant: "border-zinc-500/50",
  variable: "border-zinc-500/50",
};

interface SymbolDetailProps {
  symbol: SymbolInfo;
  repoId: string;
}

export function SymbolDetail({ symbol, repoId }: SymbolDetailProps) {
  const navigate = useNavigate();
  const crossRefs = useCrossRefs(repoId, symbol.name);
  const accent = KIND_ACCENT[symbol.kind] || "border-zinc-500/50";

  const handleFileClick = (file: string, line: number) => {
    navigate(`../files?path=${encodeURIComponent(file)}#L${line}`);
  };

  return (
    <div
      className={`border-l-2 ${accent} bg-muted/30 px-4 py-3 space-y-3 animate-in slide-in-from-top-1 duration-200`}
    >
      {/* Signature */}
      {symbol.signature && (
        <code className="block text-xs font-mono text-foreground/80 whitespace-pre-wrap">
          {symbol.signature}
        </code>
      )}

      {/* File location */}
      <div className="flex items-center gap-2">
        <button
          onClick={() => handleFileClick(symbol.file, symbol.line)}
          className="font-mono text-xs text-primary hover:underline"
        >
          {symbol.file}:L{symbol.line}
          {symbol.end_line ? `–L${symbol.end_line}` : ""}
        </button>
      </div>

      {/* Cross-references */}
      <div className="space-y-2">
        {crossRefs.isLoading && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="h-3 w-3 animate-spin" />
            Loading references...
          </div>
        )}

        {crossRefs.isError && (
          <p className="text-xs text-destructive">
            Failed to load cross-references
          </p>
        )}

        {crossRefs.data && (
          <>
            {crossRefs.data.definitions.length > 0 && (
              <div>
                <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                  Definitions ({crossRefs.data.definitions.length})
                </p>
                <div className="mt-1 space-y-0.5">
                  {crossRefs.data.definitions.map((d, i) => (
                    <button
                      key={i}
                      onClick={() => handleFileClick(d.file, d.line)}
                      className="block w-full truncate text-left font-mono text-[11px] text-muted-foreground hover:text-foreground"
                    >
                      {d.file}:{d.line}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {crossRefs.data.references.length > 0 && (
              <div>
                <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                  References ({crossRefs.data.references.length})
                </p>
                <div className="mt-1 space-y-0.5">
                  {crossRefs.data.references.map((r, i) => (
                    <button
                      key={i}
                      onClick={() => handleFileClick(r.file, r.line)}
                      className="block w-full truncate text-left font-mono text-[11px] text-muted-foreground hover:text-foreground"
                    >
                      {r.file}:{r.line}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {crossRefs.data.definitions.length > 0 &&
              crossRefs.data.references.length === 0 && (
                <p className="text-xs text-muted-foreground">
                  No call sites indexed
                </p>
              )}

            {crossRefs.data.definitions.length === 0 &&
              crossRefs.data.references.length === 0 && (
                <p className="text-xs text-muted-foreground">
                  No cross-reference data available
                </p>
              )}
          </>
        )}
      </div>

      {/* View in Files button */}
      <Button
        variant="outline"
        size="sm"
        className="gap-1.5 text-xs"
        onClick={() => handleFileClick(symbol.file, symbol.line)}
      >
        <ExternalLink className="h-3 w-3" />
        View in Files
      </Button>
    </div>
  );
}
