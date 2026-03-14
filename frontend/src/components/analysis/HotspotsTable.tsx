import { useState, useMemo } from "react";
import type { FileHotspot, FunctionHotspot } from "@/api/generated/schema";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/shared/EmptyState";
import { Flame } from "lucide-react";

const CATEGORY_CONFIG: Record<string, { color: string; label: string }> = {
  "god-file": { color: "bg-red-500/15 text-red-400 border-red-500/30", label: "God File" },
  hub: { color: "bg-blue-500/15 text-blue-400 border-blue-500/30", label: "Hub" },
  "coupling-magnet": { color: "bg-orange-500/15 text-orange-400 border-orange-500/30", label: "Coupling" },
  "wide-api": { color: "bg-purple-500/15 text-purple-400 border-purple-500/30", label: "Wide API" },
};

type SortKey = "composite" | "fan_in" | "fan_out" | "lines" | "symbols";

interface FileHotspotsTableProps {
  hotspots: FileHotspot[];
}

export function FileHotspotsTable({ hotspots }: FileHotspotsTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>("composite");
  const [sortAsc, setSortAsc] = useState(false);
  const [categoryFilter, setCategoryFilter] = useState<string | null>(null);

  const allCategories = useMemo(() => {
    const cats = new Set<string>();
    for (const h of hotspots) {
      for (const c of h.categories) cats.add(c);
    }
    return [...cats].sort();
  }, [hotspots]);

  const sorted = useMemo(() => {
    let items = categoryFilter
      ? hotspots.filter((h) => h.categories.includes(categoryFilter))
      : hotspots;
    const keyFn: Record<SortKey, (h: FileHotspot) => number> = {
      composite: (h) => h.composite,
      fan_in: (h) => h.fan_in,
      fan_out: (h) => h.fan_out,
      lines: (h) => h.line_count,
      symbols: (h) => h.symbol_count,
    };
    const fn = keyFn[sortKey];
    items = [...items].sort((a, b) => (sortAsc ? fn(a) - fn(b) : fn(b) - fn(a)));
    return items;
  }, [hotspots, sortKey, sortAsc, categoryFilter]);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortAsc(!sortAsc);
    else {
      setSortKey(key);
      setSortAsc(false);
    }
  };

  const SortHeader = ({ k, children }: { k: SortKey; children: React.ReactNode }) => (
    <TableHead
      className="cursor-pointer select-none hover:text-foreground transition-colors"
      onClick={() => toggleSort(k)}
    >
      <span className="inline-flex items-center gap-1">
        {children}
        {sortKey === k && <span className="text-primary">{sortAsc ? "\u2191" : "\u2193"}</span>}
      </span>
    </TableHead>
  );

  if (!hotspots.length) {
    return (
      <EmptyState
        icon={<Flame className="h-8 w-8" />}
        title="No hotspots found"
      />
    );
  }

  return (
    <div className="space-y-3">
      {allCategories.length > 0 && (
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-muted-foreground mr-1">Filter:</span>
          <Button
            variant={categoryFilter === null ? "default" : "outline"}
            size="sm"
            className="text-xs h-7"
            onClick={() => setCategoryFilter(null)}
          >
            All
          </Button>
          {allCategories.map((cat) => {
            const cfg = CATEGORY_CONFIG[cat];
            return (
              <Button
                key={cat}
                variant={categoryFilter === cat ? "default" : "outline"}
                size="sm"
                className="text-xs h-7"
                onClick={() => setCategoryFilter(categoryFilter === cat ? null : cat)}
              >
                {cfg?.label ?? cat}
              </Button>
            );
          })}
        </div>
      )}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>File</TableHead>
            <SortHeader k="composite">Score</SortHeader>
            <SortHeader k="fan_in">Fan-in</SortHeader>
            <SortHeader k="fan_out">Fan-out</SortHeader>
            <SortHeader k="symbols">Symbols</SortHeader>
            <SortHeader k="lines">Lines</SortHeader>
            <TableHead>Categories</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((h, i) => (
            <TableRow key={i}>
              <TableCell className="font-mono text-xs truncate max-w-sm">
                {h.path}
              </TableCell>
              <TableCell>
                <div className="flex items-center gap-2">
                  <div className="h-2 w-16 rounded-full bg-zinc-800">
                    <div
                      className="h-2 rounded-full bg-amber-500"
                      style={{ width: `${Math.min(h.composite * 100, 100)}%` }}
                    />
                  </div>
                  <span className="text-xs tabular-nums">{(h.composite * 100).toFixed(0)}%</span>
                </div>
              </TableCell>
              <TableCell className="tabular-nums">{h.fan_in}</TableCell>
              <TableCell className="tabular-nums">{h.fan_out}</TableCell>
              <TableCell className="tabular-nums">{h.symbol_count}</TableCell>
              <TableCell className="tabular-nums">{h.line_count}</TableCell>
              <TableCell>
                <div className="flex gap-1 flex-wrap">
                  {h.categories.map((cat) => {
                    const cfg = CATEGORY_CONFIG[cat];
                    return (
                      <Badge
                        key={cat}
                        variant="outline"
                        className={`text-[10px] ${cfg?.color ?? ""}`}
                      >
                        {cfg?.label ?? cat}
                      </Badge>
                    );
                  })}
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

interface FunctionHotspotsTableProps {
  hotspots: FunctionHotspot[];
}

export function FunctionHotspotsTable({ hotspots }: FunctionHotspotsTableProps) {
  if (!hotspots.length) return null;

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>File</TableHead>
          <TableHead>Name</TableHead>
          <TableHead>Lines</TableHead>
          <TableHead>Params</TableHead>
          <TableHead>Return Type</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {hotspots.map((h, i) => (
          <TableRow key={i}>
            <TableCell className="font-mono text-xs truncate max-w-xs">
              {h.file_path}
            </TableCell>
            <TableCell className="font-mono text-xs">{h.name}</TableCell>
            <TableCell className="tabular-nums">{h.line_count}</TableCell>
            <TableCell className="tabular-nums">{h.param_count}</TableCell>
            <TableCell>
              {h.has_return_type ? (
                <Badge variant="outline" className="text-[10px] bg-green-500/15 text-green-400 border-green-500/30">
                  Yes
                </Badge>
              ) : (
                <span className="text-xs text-muted-foreground">No</span>
              )}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

interface OrphanFilesListProps {
  files: FileHotspot[];
}

export function OrphanFilesList({ files }: OrphanFilesListProps) {
  if (!files.length) return null;

  return (
    <div className="space-y-1">
      <p className="text-xs text-muted-foreground mb-2">
        Files with zero fan-in and fan-out (possible dead code):
      </p>
      <div className="grid gap-1">
        {files.map((f, i) => (
          <div
            key={i}
            className="flex items-center justify-between rounded-md border border-border px-3 py-1.5 text-sm"
          >
            <span className="font-mono text-xs truncate">{f.path}</span>
            <span className="text-xs text-muted-foreground tabular-nums">{f.line_count} lines</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/** @deprecated Backwards compat wrapper */
export function HotspotsTable({ hotspots }: { hotspots: { file: string; score: number; commit_count: number; complexity: number; lines: number }[] }) {
  const mapped: FileHotspot[] = hotspots.map((h) => ({
    path: h.file,
    line_count: h.lines,
    symbol_count: h.complexity,
    public_symbols: 0,
    fan_in: 0,
    fan_out: 0,
    density: 0,
    composite: h.score,
    categories: [],
  }));
  return <FileHotspotsTable hotspots={mapped} />;
}
