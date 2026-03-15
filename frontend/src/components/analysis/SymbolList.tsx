import { useState, useMemo } from "react";
import type { SymbolInfo } from "@/api/generated/schema";
import { useSearchSymbols } from "@/api/hooks/useAnalysis";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { SymbolDetail } from "./SymbolDetail";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/shared/EmptyState";
import {
  Code2,
  ChevronDown,
  ChevronRight,
  FunctionSquare,
  Box,
  Layers,
  Type,
  Search,
  Loader2,
} from "lucide-react";

const KIND_ICONS: Record<string, typeof Code2> = {
  function: FunctionSquare,
  method: FunctionSquare,
  class: Box,
  interface: Layers,
  type: Type,
  constant: Code2,
  variable: Code2,
};

const KIND_COLORS: Record<string, string> = {
  function: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  method: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  class: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  interface: "bg-purple-500/15 text-purple-400 border-purple-500/30",
  type: "bg-green-500/15 text-green-400 border-green-500/30",
  constant: "bg-zinc-500/15 text-zinc-400 border-zinc-500/30",
  variable: "bg-zinc-500/15 text-zinc-400 border-zinc-500/30",
};

const ALL_KINDS = ["All", "Functions", "Classes", "Interfaces", "Types"] as const;
const KIND_FILTER_MAP: Record<string, string[]> = {
  All: [],
  Functions: ["function", "method"],
  Classes: ["class"],
  Interfaces: ["interface"],
  Types: ["type"],
};

interface SymbolListProps {
  symbols: SymbolInfo[];
  repoId: string;
}

export function SymbolList({ symbols, repoId }: SymbolListProps) {
  const [search, setSearch] = useState("");
  const [dirFilter, setDirFilter] = useState("");
  const [kindFilter, setKindFilter] = useState<string>("All");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [expandedSymbol, setExpandedSymbol] = useState<string | null>(null);

  const debouncedSearch = useDebouncedValue(search, 150);
  const serverSearch = useSearchSymbols(repoId, debouncedSearch, dirFilter || undefined);

  const effectiveSymbols =
    debouncedSearch && serverSearch.data
      ? serverSearch.data.definitions
      : symbols;

  const filtered = useMemo(() => {
    let items = effectiveSymbols;
    // Only apply client-side text filter when not using server results
    if (debouncedSearch && !serverSearch.data) {
      const q = debouncedSearch.toLowerCase();
      items = items.filter(
        (s) =>
          s.name.toLowerCase().includes(q) ||
          s.file?.toLowerCase().includes(q),
      );
    }
    const kinds = KIND_FILTER_MAP[kindFilter];
    if (kinds && kinds.length > 0) {
      items = items.filter((s) => kinds.includes(s.kind));
    }
    return items;
  }, [effectiveSymbols, debouncedSearch, serverSearch.data, kindFilter]);

  const grouped = useMemo(() => {
    const groups = new Map<string, SymbolInfo[]>();
    for (const sym of filtered) {
      const file = sym.file || "(unknown)";
      if (!groups.has(file)) groups.set(file, []);
      groups.get(file)!.push(sym);
    }
    return [...groups.entries()].sort((a, b) => b[1].length - a[1].length);
  }, [filtered]);

  const toggleExpand = (file: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(file)) next.delete(file);
      else next.add(file);
      return next;
    });
  };

  const toggleSymbolDetail = (key: string) => {
    setExpandedSymbol((prev) => (prev === key ? null : key));
  };

  if (!symbols.length) {
    return (
      <EmptyState
        icon={<Code2 className="h-8 w-8" />}
        title="No symbols found"
        description="Symbols will appear after the repository is indexed"
      />
    );
  }

  return (
    <div className="space-y-3">
      {/* Controls */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search symbols..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
          />
          {serverSearch.isFetching && debouncedSearch && (
            <Loader2 className="absolute right-2.5 top-2.5 h-4 w-4 text-muted-foreground animate-spin" />
          )}
        </div>
        <Input
          placeholder="Directory filter..."
          value={dirFilter}
          onChange={(e) => setDirFilter(e.target.value)}
          className="w-48 text-xs"
        />
        <div className="flex gap-1">
          {ALL_KINDS.map((kind) => (
            <Button
              key={kind}
              variant={kindFilter === kind ? "default" : "outline"}
              size="sm"
              onClick={() => setKindFilter(kind)}
              className="text-xs"
            >
              {kind}
            </Button>
          ))}
        </div>
      </div>

      <div className="text-xs text-muted-foreground">
        {filtered.length} symbols in {grouped.length} files
        {debouncedSearch && serverSearch.data && (
          <span className="ml-1 text-primary/70">(server search)</span>
        )}
      </div>

      {/* Grouped symbol list */}
      <div className="space-y-1">
        {grouped.map(([file, syms]) => {
          const isCollapsed = !expanded.has(file);
          return (
            <div
              key={file}
              className="rounded-lg border border-border bg-card overflow-hidden"
            >
              {/* File header */}
              <button
                onClick={() => toggleExpand(file)}
                className="flex items-center gap-2 w-full px-3 py-2 text-left hover:bg-muted/50 transition-colors"
              >
                {isCollapsed ? (
                  <ChevronRight className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                ) : (
                  <ChevronDown className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                )}
                <span className="font-mono text-xs text-muted-foreground truncate">
                  {file}
                </span>
                <Badge
                  variant="secondary"
                  className="ml-auto shrink-0 text-[10px]"
                >
                  {syms.length}
                </Badge>
              </button>

              {/* Symbols */}
              {!isCollapsed && (
                <div className="border-t border-border">
                  {syms.map((sym, i) => {
                    const Icon = KIND_ICONS[sym.kind] || Code2;
                    const colorClass =
                      KIND_COLORS[sym.kind] ||
                      "bg-zinc-500/15 text-zinc-400 border-zinc-500/30";
                    const symKey = `${sym.name}-${sym.line}-${i}`;
                    const isExpanded = expandedSymbol === symKey;
                    return (
                      <div key={symKey}>
                        <button
                          onClick={() => toggleSymbolDetail(symKey)}
                          className={`flex items-center gap-2.5 w-full px-3 py-1.5 text-left hover:bg-muted/40 transition-colors ${isExpanded ? "bg-muted/30" : ""}`}
                        >
                          <Badge
                            variant="outline"
                            className={`shrink-0 text-[10px] px-1.5 py-0 gap-1 ${colorClass}`}
                          >
                            <Icon className="h-3 w-3" />
                            {sym.kind}
                          </Badge>
                          <span className="font-mono text-sm truncate">
                            {sym.name}
                          </span>
                          {sym.signature && (
                            <span className="font-mono text-xs text-muted-foreground truncate">
                              {sym.signature}
                            </span>
                          )}
                          <span className="ml-auto text-xs text-muted-foreground shrink-0 tabular-nums">
                            L{sym.line}
                          </span>
                        </button>
                        {isExpanded && (
                          <SymbolDetail symbol={sym} repoId={repoId} />
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
