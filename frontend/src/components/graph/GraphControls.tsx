import { useState, useEffect, useRef } from "react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Network, Search, FolderSearch } from "lucide-react";
import { useFileTree } from "@/api/hooks/useFiles";
import { FileTree } from "@/components/code/FileTree";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";

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
  orgId: string;
  repoId: string;
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
  orgId,
  repoId,
}: GraphControlsProps) {
  const [showBrowser, setShowBrowser] = useState(false);
  const browserRef = useRef<HTMLDivElement>(null);
  const fileTree = useFileTree(orgId, repoId);

  useEffect(() => {
    if (!showBrowser) return;
    const handler = (e: MouseEvent) => {
      if (browserRef.current && !browserRef.current.contains(e.target as Node)) {
        setShowBrowser(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [showBrowser]);

  const handleSelect = (path: string) => {
    onFileChange(path);
    setShowBrowser(false);
    // Auto-trigger graph generation when a file/dir is selected from browser
    setTimeout(() => onGenerate(), 0);
  };

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
        <div className="relative" ref={browserRef}>
          <Button onClick={() => setShowBrowser(!showBrowser)} className="gap-1.5">
            <FolderSearch className="h-4 w-4" />
            Select File or Directory
          </Button>
          {showBrowser && (
            <div className="absolute left-0 top-full z-50 mt-1 w-96 max-h-[28rem] rounded-lg border border-border bg-background shadow-lg flex flex-col">
              <div className="p-2 border-b border-border">
                <div className="relative">
                  <Search className="absolute left-2.5 top-2 h-3.5 w-3.5 text-muted-foreground" />
                  <Input
                    placeholder="Filter files..."
                    className="h-8 pl-8 text-xs"
                    autoFocus
                    onChange={(e) => {
                      const val = e.target.value.trim();
                      if (val) onFileChange(val);
                    }}
                  />
                </div>
              </div>
              <div className="flex-1 overflow-auto">
                {fileTree.isLoading ? (
                  <div className="p-4"><LoadingSpinner /></div>
                ) : fileTree.data?.tree ? (
                  <div className="p-1">
                    <FileTree
                      nodes={fileTree.data.tree}
                      onSelect={handleSelect}
                      onSelectDirectory={handleSelect}
                      selectedPath={file}
                    />
                  </div>
                ) : (
                  <div className="p-4 text-sm text-muted-foreground">No files found</div>
                )}
              </div>
            </div>
          )}
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
