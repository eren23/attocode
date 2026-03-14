import type {
  DependencyGraphNode,
  DependencyGraphEdge,
} from "@/api/generated/schema";
import { X, ExternalLink, FolderOpen } from "lucide-react";
import { Button } from "@/components/ui/button";

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

function getExtColor(label: string): string {
  const ext = label.split(".").pop()?.toLowerCase() || "";
  return EXT_COLORS[ext] || "#6366f1";
}

interface NodeInfoCardProps {
  node: DependencyGraphNode | null;
  position: { x: number; y: number };
  edges: DependencyGraphEdge[];
  onClose: () => void;
  onNavigateToFile: (path: string) => void;
  onSelectNode: (nodeId: string) => void;
  onFocusDirectory?: (dir: string) => void;
}

export function NodeInfoCard({
  node,
  position,
  edges,
  onClose,
  onNavigateToFile,
  onSelectNode,
  onFocusDirectory,
}: NodeInfoCardProps) {
  if (!node) return null;

  const incoming = edges.filter((e) => e.target === node.id);
  const outgoing = edges.filter((e) => e.source === node.id);
  const color = getExtColor(node.label);

  // Extract directory from node label
  const lastSlash = node.label.lastIndexOf("/");
  const directory = lastSlash > 0 ? node.label.substring(0, lastSlash) : null;

  // Clamp position so card stays within container
  const style = {
    left: Math.min(position.x + 12, window.innerWidth - 340),
    top: Math.max(position.y - 12, 8),
  };

  return (
    <div
      className="absolute z-50 w-80 max-h-96 overflow-y-auto rounded-lg border border-zinc-700 bg-zinc-900/95 shadow-xl backdrop-blur-sm"
      style={style}
    >
      {/* Header */}
      <div className="sticky top-0 flex items-start justify-between gap-2 border-b border-zinc-700/50 bg-zinc-900/95 px-3 py-2.5">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span
              className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
              style={{ backgroundColor: color }}
            />
            <span className="truncate font-mono text-xs text-zinc-200">
              {node.label}
            </span>
          </div>
          <p className="mt-1 text-[10px] text-zinc-500">
            {incoming.length} incoming, {outgoing.length} outgoing
          </p>
        </div>
        <button
          onClick={onClose}
          className="shrink-0 rounded p-0.5 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-300"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Connections */}
      <div className="space-y-2 px-3 py-2">
        {incoming.length > 0 && (
          <div>
            <p className="text-[10px] font-medium uppercase tracking-wider text-zinc-500">
              Incoming ({incoming.length})
            </p>
            <div className="mt-1 space-y-0.5">
              {incoming.map((e, i) => (
                <button
                  key={i}
                  onClick={() => onSelectNode(e.source)}
                  className="block w-full truncate rounded px-1.5 py-0.5 text-left font-mono text-[11px] text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
                >
                  {e.source}
                </button>
              ))}
            </div>
          </div>
        )}

        {outgoing.length > 0 && (
          <div>
            <p className="text-[10px] font-medium uppercase tracking-wider text-zinc-500">
              Outgoing ({outgoing.length})
            </p>
            <div className="mt-1 space-y-0.5">
              {outgoing.map((e, i) => (
                <button
                  key={i}
                  onClick={() => onSelectNode(e.target)}
                  className="block w-full truncate rounded px-1.5 py-0.5 text-left font-mono text-[11px] text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
                >
                  {e.target}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="border-t border-zinc-700/50 px-3 py-2 space-y-1.5">
        <Button
          variant="outline"
          size="sm"
          className="w-full gap-1.5 text-xs"
          onClick={() => onNavigateToFile(node.label)}
        >
          <ExternalLink className="h-3 w-3" />
          Open in Files
        </Button>
        {directory && onFocusDirectory && (
          <Button
            variant="outline"
            size="sm"
            className="w-full gap-1.5 text-xs"
            onClick={() => onFocusDirectory(directory)}
          >
            <FolderOpen className="h-3 w-3" />
            Focus on this directory
          </Button>
        )}
      </div>
    </div>
  );
}
