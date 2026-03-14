import { useState, useRef } from "react";
import { useParams, useNavigate } from "react-router";
import { useSecurityScan } from "@/api/hooks/useAnalysis";
import { EmptyState } from "@/components/shared/EmptyState";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import type { SecurityFinding } from "@/api/generated/schema";
import {
  Shield,
  ShieldAlert,
  AlertTriangle,
  Info,
  FileCode2,
  FolderSearch,
} from "lucide-react";

const SEVERITIES = ["critical", "error", "warning", "info"] as const;
type Severity = (typeof SEVERITIES)[number];

const SEVERITY_CONFIG: Record<
  Severity,
  { color: string; bg: string; border: string; icon: typeof Shield; label: string }
> = {
  critical: {
    color: "text-red-400",
    bg: "bg-red-500/15",
    border: "border-red-500/30",
    icon: ShieldAlert,
    label: "Critical",
  },
  error: {
    color: "text-orange-400",
    bg: "bg-orange-500/15",
    border: "border-orange-500/30",
    icon: ShieldAlert,
    label: "Error",
  },
  warning: {
    color: "text-amber-400",
    bg: "bg-amber-500/15",
    border: "border-amber-500/30",
    icon: AlertTriangle,
    label: "Warning",
  },
  info: {
    color: "text-blue-400",
    bg: "bg-blue-500/15",
    border: "border-blue-500/30",
    icon: Info,
    label: "Info",
  },
};

function SeverityBadge({ severity }: { severity: Severity }) {
  const cfg = SEVERITY_CONFIG[severity];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium",
        cfg.color,
        cfg.bg,
        cfg.border,
      )}
    >
      <cfg.icon className="h-3 w-3" />
      {severity}
    </span>
  );
}

export function SecurityPage() {
  const { repoId } = useParams();
  const navigate = useNavigate();
  const scan = useSecurityScan(repoId!);
  const [mode, setMode] = useState("quick");
  const [path, setPath] = useState("");
  const [showPathInput, setShowPathInput] = useState(false);
  const [activeSeverities, setActiveSeverities] = useState<Set<Severity>>(
    new Set(SEVERITIES),
  );
  const scanStartTime = useRef<number | null>(null);
  const [scanDuration, setScanDuration] = useState<number | null>(null);

  const toggleSeverity = (s: Severity) => {
    setActiveSeverities((prev) => {
      const next = new Set(prev);
      if (next.has(s)) {
        next.delete(s);
      } else {
        next.add(s);
      }
      return next;
    });
  };

  const handleScan = () => {
    scanStartTime.current = Date.now();
    setScanDuration(null);
    scan.mutate(
      { mode, path: path || undefined },
      {
        onSettled: () => {
          if (scanStartTime.current) {
            setScanDuration((Date.now() - scanStartTime.current) / 1000);
          }
        },
      },
    );
  };

  const handleFileClick = (file: string, line: number | null) => {
    const hash = line ? `#L${line}` : "";
    navigate(`../files?path=${encodeURIComponent(file)}${hash}`);
  };

  const findings = scan.data?.findings ?? [];
  const filtered = findings.filter((f) =>
    activeSeverities.has(f.severity as Severity),
  );

  // Group by severity in priority order
  const grouped = SEVERITIES.map((sev) => ({
    severity: sev,
    items: filtered.filter((f) => f.severity === sev),
  })).filter((g) => g.items.length > 0);

  // Severity counts for stat cards
  const severityCounts = Object.fromEntries(
    SEVERITIES.map((sev) => [sev, findings.filter((f) => f.severity === sev).length]),
  ) as Record<Severity, number>;

  return (
    <div className="space-y-6 max-w-4xl">
      {/* Controls */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-lg">
            <Shield className="h-5 w-5" />
            Security Scanner
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Mode toggle */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">
              Scan Mode
            </label>
            <div className="flex rounded-md border border-border">
              <button
                onClick={() => setMode("quick")}
                className={cn(
                  "flex-1 rounded-l-md px-4 py-2.5 text-sm transition-colors",
                  mode === "quick"
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:text-foreground hover:bg-accent/50",
                )}
              >
                <div className="font-medium">Quick</div>
                <div className={cn("text-[10px] mt-0.5", mode === "quick" ? "text-primary-foreground/70" : "text-muted-foreground")}>
                  Pattern matching, fast
                </div>
              </button>
              <button
                onClick={() => setMode("full")}
                className={cn(
                  "flex-1 rounded-r-md border-l border-border px-4 py-2.5 text-sm transition-colors",
                  mode === "full"
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:text-foreground hover:bg-accent/50",
                )}
              >
                <div className="font-medium">Full</div>
                <div className={cn("text-[10px] mt-0.5", mode === "full" ? "text-primary-foreground/70" : "text-muted-foreground")}>
                  Deep analysis, slower
                </div>
              </button>
            </div>
          </div>

          {/* Path input (revealed on click) */}
          {showPathInput && (
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">
                Path
              </label>
              <input
                type="text"
                value={path}
                onChange={(e) => setPath(e.target.value)}
                placeholder="e.g. src/ or src/main.py"
                className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-violet-500"
              />
            </div>
          )}

          {/* Action buttons */}
          <div className="flex items-center gap-3">
            <Button
              size="lg"
              onClick={handleScan}
              disabled={scan.isPending}
              className="gap-2"
            >
              <Shield className="h-4 w-4" />
              {scan.isPending ? "Scanning..." : "Scan Repository"}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setShowPathInput((v) => !v);
                if (showPathInput) setPath("");
              }}
              className="gap-1.5"
            >
              <FolderSearch className="h-3.5 w-3.5" />
              {showPathInput ? "Clear Path" : "Scan Path..."}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Animated progress bar during scan */}
      {scan.isPending && (
        <div className="w-full overflow-hidden rounded-full bg-muted h-2">
          <div
            className="h-full rounded-full bg-violet-500 animate-pulse"
            style={{
              width: "100%",
              animation: "pulse 1.5s ease-in-out infinite, indeterminate 2s ease-in-out infinite",
              background: "linear-gradient(90deg, transparent, #8b5cf6 50%, transparent)",
              backgroundSize: "200% 100%",
            }}
          />
        </div>
      )}

      {scan.isError && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
          <strong>Scan failed:</strong>{" "}
          {scan.error?.message ?? "Unknown error"}
        </div>
      )}

      {/* Results */}
      {scan.data && (
        <>
          {/* Summary bar with duration */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <p className="text-sm text-muted-foreground">
                {scan.data.total_findings} finding
                {scan.data.total_findings !== 1 ? "s" : ""} found
                {scan.data.path ? ` in ${scan.data.path}` : ""} ({scan.data.mode}{" "}
                scan)
              </p>
              {scanDuration !== null && (
                <Badge variant="secondary" className="text-xs">
                  Completed in {scanDuration.toFixed(1)}s
                </Badge>
              )}
            </div>
          </div>

          {/* Severity stat cards grid */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {SEVERITIES.map((sev) => {
              const count = severityCounts[sev];
              const active = activeSeverities.has(sev);
              const cfg = SEVERITY_CONFIG[sev];
              const Icon = cfg.icon;
              return (
                <button
                  key={sev}
                  onClick={() => toggleSeverity(sev)}
                  className={cn(
                    "rounded-lg border p-4 text-left transition-all",
                    active
                      ? cn(cfg.bg, cfg.border, "ring-1 ring-inset", cfg.border)
                      : "border-border bg-card opacity-40 hover:opacity-60",
                  )}
                >
                  <div className="flex items-center justify-between">
                    <Icon className={cn("h-5 w-5", active ? cfg.color : "text-muted-foreground")} />
                    <span className={cn("text-2xl font-bold tabular-nums", active ? cfg.color : "text-muted-foreground")}>
                      {count}
                    </span>
                  </div>
                  <p className={cn("mt-1 text-xs font-medium capitalize", active ? cfg.color : "text-muted-foreground")}>
                    {cfg.label}
                  </p>
                </button>
              );
            })}
          </div>

          {/* Findings grouped by severity */}
          {filtered.length === 0 ? (
            <EmptyState
              icon={<Shield className="h-12 w-12" />}
              title="No findings match"
              description="Adjust filters to see results, or all findings are filtered out."
            />
          ) : (
            <div className="space-y-6">
              {grouped.map(({ severity, items }) => (
                <div key={severity} className="space-y-2">
                  <h3 className="flex items-center gap-2 text-sm font-medium capitalize">
                    <SeverityBadge severity={severity} />
                    <span className="text-muted-foreground">
                      {items.length} finding{items.length !== 1 ? "s" : ""}
                    </span>
                  </h3>
                  <div className="space-y-2">
                    {items.map((finding, idx) => (
                      <FindingRow
                        key={`${finding.file}-${finding.line}-${finding.rule}-${idx}`}
                        finding={finding}
                        onFileClick={handleFileClick}
                      />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {!scan.data && !scan.isPending && !scan.isError && (
        <EmptyState
          icon={<Shield className="h-12 w-12" />}
          title="Security Scanner"
          description="Run a scan to check for security issues in your codebase."
        />
      )}
    </div>
  );
}

function FindingRow({
  finding,
  onFileClick,
}: {
  finding: SecurityFinding;
  onFileClick: (file: string, line: number | null) => void;
}) {
  const cfg = SEVERITY_CONFIG[finding.severity as Severity];

  return (
    <div
      className={cn(
        "rounded-lg border px-4 py-3 text-sm",
        cfg.border,
        "bg-card",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex items-center gap-2 flex-wrap">
            <SeverityBadge severity={finding.severity as Severity} />
            <Badge variant="outline" className="font-mono text-xs">
              {finding.rule}
            </Badge>
            {finding.category && (
              <span className="text-xs text-muted-foreground">
                {finding.category}
              </span>
            )}
          </div>
          <p className="text-foreground">{finding.message}</p>
          {finding.suggestion && (
            <p className="text-xs text-muted-foreground">
              Suggestion: {finding.suggestion}
            </p>
          )}
        </div>
        <button
          onClick={() => onFileClick(finding.file, finding.line)}
          className="flex shrink-0 items-center gap-1.5 rounded-md px-2 py-1 text-xs font-mono text-muted-foreground hover:text-foreground hover:bg-accent/50 transition-colors"
          title="Open file"
        >
          <FileCode2 className="h-3.5 w-3.5" />
          {finding.file}
          {finding.line != null && (
            <span className={cfg.color}>:{finding.line}</span>
          )}
        </button>
      </div>
    </div>
  );
}
