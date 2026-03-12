import type { DependencyGraphNode } from "@/api/generated/schema";

interface GraphTooltipProps {
  node: DependencyGraphNode | null;
  position: { x: number; y: number };
}

export function GraphTooltip({ node, position }: GraphTooltipProps) {
  if (!node) return null;

  return (
    <div
      className="pointer-events-none absolute z-50 rounded-md border border-border bg-popover px-3 py-2 text-sm shadow-md"
      style={{ left: position.x + 10, top: position.y - 10 }}
    >
      <p className="font-mono text-xs">{node.label}</p>
      <p className="text-xs text-muted-foreground">Type: {node.type}</p>
    </div>
  );
}
