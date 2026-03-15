import type { DependencyGraphNode } from "@/api/generated/schema";

interface GraphTooltipProps {
  node: DependencyGraphNode | null;
  position: { x: number; y: number };
  connectionCount: number;
  incomingCount: number;
  outgoingCount: number;
}

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
};

function getExtColor(label: string): string {
  const ext = label.split(".").pop()?.toLowerCase() || "";
  return EXT_COLORS[ext] || "#6366f1";
}

export function GraphTooltip({
  node,
  position,
  connectionCount,
  incomingCount,
  outgoingCount,
}: GraphTooltipProps) {
  if (!node) return null;

  const color = getExtColor(node.label);

  return (
    <div
      className="pointer-events-none absolute z-50 rounded-lg border border-border bg-card/95 px-3 py-2.5 shadow-lg backdrop-blur-sm"
      style={{ left: position.x + 12, top: position.y - 12 }}
    >
      <p className="font-mono text-xs text-foreground">{node.label}</p>
      <div className="mt-1.5 flex items-center gap-2">
        <span
          className="inline-block h-2 w-2 rounded-full"
          style={{ backgroundColor: color }}
        />
        <span className="text-[10px] text-muted-foreground">{node.type}</span>
      </div>
      <p className="mt-1 text-[10px] text-muted-foreground">
        {connectionCount} connections ({incomingCount} in, {outgoingCount} out)
      </p>
    </div>
  );
}
