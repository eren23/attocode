import { useState } from "react";
import type { ConventionsData, ConventionStats } from "@/api/generated/schema";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/shared/EmptyState";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { BookOpen, ChevronDown, ChevronRight } from "lucide-react";

function pct(n: number, total: number): string {
  if (total === 0) return "0";
  return ((n / total) * 100).toFixed(0);
}

function ProgressBar({ value, max, color = "bg-primary" }: { value: number; max: number; color?: string }) {
  const p = max > 0 ? Math.min((value / max) * 100, 100) : 0;
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 flex-1 rounded-full bg-zinc-800">
        <div className={`h-2 rounded-full ${color}`} style={{ width: `${p}%` }} />
      </div>
      <span className="text-xs text-muted-foreground tabular-nums w-10 text-right">{pct(value, max)}%</span>
    </div>
  );
}

function OverviewCards({ stats }: { stats: ConventionStats }) {
  const totalFn = stats.total_functions || 0;
  const totalCls = stats.total_classes || 0;
  const namingPct = totalFn > 0 ? Math.max(stats.snake_names, stats.camel_names) / totalFn : 0;
  const typePct = totalFn > 0 ? stats.typed_return / totalFn : 0;
  const asyncPct = totalFn > 0 ? stats.async_count / totalFn : 0;
  const docPct = totalCls > 0 ? stats.has_docstring_cls / totalCls : 0;

  const cards = [
    { label: "Naming Consistency", value: namingPct, sub: stats.snake_names > stats.camel_names ? "snake_case" : "camelCase" },
    { label: "Type Annotations", value: typePct, sub: `${stats.typed_return}/${totalFn} typed` },
    { label: "Async Usage", value: asyncPct, sub: `${stats.async_count} async functions` },
    { label: "Documentation", value: docPct, sub: `${stats.has_docstring_cls}/${totalCls} classes` },
  ];

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      {cards.map((c) => (
        <Card key={c.label}>
          <CardContent className="pt-4 pb-3">
            <p className="text-xs font-medium text-muted-foreground mb-2">{c.label}</p>
            <ProgressBar value={c.value * 100} max={100} />
            <p className="text-xs text-muted-foreground mt-1">{c.sub}</p>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function ImportPatterns({ stats }: { stats: ConventionStats }) {
  const total = stats.from_imports + stats.plain_imports + stats.relative_imports;
  if (total === 0) return null;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Import Patterns</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex h-4 w-full rounded-full overflow-hidden">
          {stats.from_imports > 0 && (
            <div
              className="bg-blue-500 h-full"
              style={{ width: `${(stats.from_imports / total) * 100}%` }}
              title={`from imports: ${stats.from_imports}`}
            />
          )}
          {stats.plain_imports > 0 && (
            <div
              className="bg-green-500 h-full"
              style={{ width: `${(stats.plain_imports / total) * 100}%` }}
              title={`plain imports: ${stats.plain_imports}`}
            />
          )}
          {stats.relative_imports > 0 && (
            <div
              className="bg-amber-500 h-full"
              style={{ width: `${(stats.relative_imports / total) * 100}%` }}
              title={`relative imports: ${stats.relative_imports}`}
            />
          )}
        </div>
        <div className="flex gap-4 mt-2 text-xs text-muted-foreground">
          <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-blue-500" />from: {stats.from_imports}</span>
          <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-green-500" />plain: {stats.plain_imports}</span>
          <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-amber-500" />relative: {stats.relative_imports}</span>
        </div>
      </CardContent>
    </Card>
  );
}

function ClassPatterns({ stats }: { stats: ConventionStats }) {
  if (stats.total_classes === 0 && stats.dataclass_count === 0) return null;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Class Patterns</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-3 gap-4 text-center">
          <div>
            <p className="text-2xl font-semibold tabular-nums">{stats.dataclass_count}</p>
            <p className="text-xs text-muted-foreground">Dataclasses</p>
          </div>
          <div>
            <p className="text-2xl font-semibold tabular-nums">{stats.abstract_count}</p>
            <p className="text-xs text-muted-foreground">Abstract</p>
          </div>
          <div>
            <p className="text-2xl font-semibold tabular-nums">{stats.exception_classes.length}</p>
            <p className="text-xs text-muted-foreground">Exceptions</p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function MethodDecorators({ stats }: { stats: ConventionStats }) {
  if (stats.staticmethod_count === 0 && stats.classmethod_count === 0 && stats.property_count === 0) return null;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Method Decorators</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-3 gap-4 text-center">
          <div>
            <p className="text-2xl font-semibold tabular-nums">{stats.staticmethod_count}</p>
            <p className="text-xs text-muted-foreground">@staticmethod</p>
          </div>
          <div>
            <p className="text-2xl font-semibold tabular-nums">{stats.classmethod_count}</p>
            <p className="text-xs text-muted-foreground">@classmethod</p>
          </div>
          <div>
            <p className="text-2xl font-semibold tabular-nums">{stats.property_count}</p>
            <p className="text-xs text-muted-foreground">@property</p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function DirectoryComparison({ dirStats, projectStats }: { dirStats: Record<string, ConventionStats>; projectStats: ConventionStats }) {
  const [expanded, setExpanded] = useState(false);
  const dirs = Object.entries(dirStats);
  if (dirs.length === 0) return null;

  const projNaming = projectStats.total_functions > 0
    ? (Math.max(projectStats.snake_names, projectStats.camel_names) / projectStats.total_functions) * 100
    : 0;
  const projTyped = projectStats.total_functions > 0
    ? (projectStats.typed_return / projectStats.total_functions) * 100
    : 0;

  return (
    <Card>
      <CardHeader
        className="pb-2 cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        <CardTitle className="flex items-center gap-2 text-sm">
          {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          Directory Comparison
          <Badge variant="secondary" className="text-[10px]">{dirs.length} dirs</Badge>
        </CardTitle>
      </CardHeader>
      {expanded && (
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Directory</TableHead>
                <TableHead>Functions</TableHead>
                <TableHead>Classes</TableHead>
                <TableHead>Naming %</TableHead>
                <TableHead>Typed %</TableHead>
                <TableHead>Async</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {dirs.sort((a, b) => b[1].total_functions - a[1].total_functions).map(([dir, s]) => {
                const naming = s.total_functions > 0
                  ? (Math.max(s.snake_names, s.camel_names) / s.total_functions) * 100
                  : 0;
                const typed = s.total_functions > 0
                  ? (s.typed_return / s.total_functions) * 100
                  : 0;
                const namingDeviation = Math.abs(naming - projNaming) > 20;
                const typedDeviation = Math.abs(typed - projTyped) > 20;

                return (
                  <TableRow key={dir}>
                    <TableCell className="font-mono text-xs truncate max-w-xs">{dir}</TableCell>
                    <TableCell className="tabular-nums">{s.total_functions}</TableCell>
                    <TableCell className="tabular-nums">{s.total_classes}</TableCell>
                    <TableCell className={`tabular-nums ${namingDeviation ? "text-amber-400" : ""}`}>
                      {naming.toFixed(0)}%
                    </TableCell>
                    <TableCell className={`tabular-nums ${typedDeviation ? "text-amber-400" : ""}`}>
                      {typed.toFixed(0)}%
                    </TableCell>
                    <TableCell className="tabular-nums">{s.async_count}</TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
          <p className="text-[10px] text-muted-foreground mt-2">
            Amber values deviate &gt;20% from project norm
          </p>
        </CardContent>
      )}
    </Card>
  );
}

interface ConventionsPanelNewProps {
  data: ConventionsData;
}

export function ConventionsPanelNew({ data }: ConventionsPanelNewProps) {
  const { stats, dir_stats } = data;

  if (stats.total_functions === 0 && stats.total_classes === 0) {
    return (
      <EmptyState
        icon={<BookOpen className="h-8 w-8" />}
        title="No conventions detected"
        description="No functions or classes found to analyze"
      />
    );
  }

  return (
    <div className="space-y-4 max-w-4xl">
      <div className="flex items-center gap-3 text-sm text-muted-foreground">
        <span>Sample: {data.sample_size} files</span>
        {data.path && <Badge variant="outline" className="font-mono text-xs">{data.path}</Badge>}
      </div>

      <OverviewCards stats={stats} />

      <div className="grid md:grid-cols-2 gap-4">
        <ImportPatterns stats={stats} />
        <ClassPatterns stats={stats} />
      </div>

      <MethodDecorators stats={stats} />
      <DirectoryComparison dirStats={dir_stats} projectStats={stats} />
    </div>
  );
}

/** @deprecated Backwards compat */
export function ConventionsPanel({
  conventions,
}: {
  conventions: { category: string; pattern: string; examples: string[]; confidence: number }[];
}) {
  if (!conventions.length) {
    return (
      <EmptyState
        icon={<BookOpen className="h-8 w-8" />}
        title="No conventions detected"
      />
    );
  }

  return (
    <div className="grid gap-4 md:grid-cols-2">
      {conventions.map((conv, i) => (
        <Card key={i}>
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm">{conv.category}</CardTitle>
              <Badge variant="outline">
                {(conv.confidence * 100).toFixed(0)}%
              </Badge>
            </div>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground mb-2">{conv.pattern}</p>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
