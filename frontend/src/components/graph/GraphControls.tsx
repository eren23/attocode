import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Network, Search } from "lucide-react";

interface GraphControlsProps {
  file: string;
  depth: number;
  onFileChange: (file: string) => void;
  onDepthChange: (depth: number) => void;
  onGenerate: () => void;
  loading: boolean;
  layoutMode: "force" | "dagre";
  onLayoutModeChange: (mode: "force" | "dagre") => void;
  searchQuery: string;
  onSearchChange: (query: string) => void;
  nodeCount?: number;
  edgeCount?: number;
}

export function GraphControls({
  file,
  depth,
  onFileChange,
  onDepthChange,
  onGenerate,
  loading,
  layoutMode,
  onLayoutModeChange,
  searchQuery,
  onSearchChange,
  nodeCount,
  edgeCount,
}: GraphControlsProps) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-end gap-3">
        <div className="flex-1 space-y-1">
          <label className="text-xs font-medium text-muted-foreground">
            Path
          </label>
          <Input
            placeholder="e.g. src/api/ or src/main.ts"
            value={file}
            onChange={(e) => onFileChange(e.target.value)}
          />
        </div>
        <div className="w-24 space-y-1">
          <label className="text-xs font-medium text-muted-foreground">
            Depth
          </label>
          <Input
            type="number"
            min={1}
            max={10}
            value={depth}
            onChange={(e) => onDepthChange(Number(e.target.value))}
          />
        </div>
        <Button onClick={onGenerate} disabled={loading}>
          <Network className="h-4 w-4" />
          {loading ? "Generating..." : "Generate"}
        </Button>
        {nodeCount != null && edgeCount != null && (nodeCount > 0 || edgeCount > 0) && (
          <Badge variant="secondary" className="whitespace-nowrap">
            {nodeCount} nodes, {edgeCount} edges
          </Badge>
        )}
      </div>
      <div className="flex items-center gap-3">
        {/* Layout mode toggle */}
        <div className="flex rounded-md border border-border">
          <button
            onClick={() => onLayoutModeChange("force")}
            className={`px-3 py-1.5 text-xs transition-colors ${
              layoutMode === "force"
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:text-foreground"
            } rounded-l-md`}
          >
            Force
          </button>
          <button
            onClick={() => onLayoutModeChange("dagre")}
            className={`px-3 py-1.5 text-xs transition-colors ${
              layoutMode === "dagre"
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:text-foreground"
            } rounded-r-md`}
          >
            Dagre
          </button>
        </div>
        {/* Node search */}
        <div className="relative flex-1">
          <Search className="absolute left-2.5 top-2 h-3.5 w-3.5 text-muted-foreground" />
          <Input
            placeholder="Search nodes..."
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            className="h-8 pl-8 text-xs"
          />
        </div>
      </div>
    </div>
  );
}
