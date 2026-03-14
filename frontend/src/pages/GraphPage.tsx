import { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router";
import { useDependencyGraph } from "@/api/hooks/useGraph";
import { useCommunities } from "@/api/hooks/useAnalysis";
import { DependencyGraph } from "@/components/graph/DependencyGraph";
import { GraphControls } from "@/components/graph/GraphControls";
import { NodeInfoCard } from "@/components/graph/NodeInfoCard";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { EmptyState } from "@/components/shared/EmptyState";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { DependencyGraphNode } from "@/api/generated/schema";
import { Network, ArrowRight, ArrowDown, Layers } from "lucide-react";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";

// Community color palette for node overlay
const COMMUNITY_COLORS = [
  "#8b5cf6", "#06b6d4", "#f59e0b", "#ef4444", "#10b981",
  "#ec4899", "#3b82f6", "#f97316", "#14b8a6", "#a855f7",
  "#6366f1", "#84cc16", "#e11d48", "#0ea5e9", "#d946ef",
];

export function GraphPage() {
  const { repoId } = useParams();
  const navigate = useNavigate();
  const graph = useDependencyGraph(repoId!);
  const communities = useCommunities(repoId!);
  const [file, setFile] = useState("");
  const [depth, setDepth] = useState(2);
  const [direction, setDirection] = useState<"LR" | "TB">("LR");
  const [layoutMode, setLayoutMode] = useState<"force" | "dagre">("dagre");
  const [graphSearch, setGraphSearch] = useState("");
  const debouncedGraphSearch = useDebouncedValue(graphSearch, 300);
  const [showCommunities, setShowCommunities] = useState(false);

  const [selectedNode, setSelectedNode] = useState<DependencyGraphNode | null>(null);
  const [selectedNodePos, setSelectedNodePos] = useState({ x: 0, y: 0 });

  // Build community color map for nodes
  const communityColorMap = useCallback(() => {
    if (!showCommunities || !communities.data?.communities) return undefined;
    const map: Record<string, string> = {};
    for (const [i, c] of communities.data.communities.entries()) {
      const color = COMMUNITY_COLORS[i % COMMUNITY_COLORS.length]!;
      for (const f of c.files) {
        map[f] = color;
      }
    }
    return map;
  }, [showCommunities, communities.data]);

  // Close card on Esc
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setSelectedNode(null);
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, []);

  const handleGenerate = () => {
    graph.mutate({ file: file || undefined, depth });
  };

  const handleNodeSelect = useCallback(
    (node: DependencyGraphNode, position: { x: number; y: number }) => {
      setSelectedNode(node);
      setSelectedNodePos(position);
    },
    [],
  );

  const handleNavigateToFile = useCallback(
    (path: string) => {
      navigate(`../files?path=${encodeURIComponent(path)}`);
    },
    [navigate],
  );

  const handleSelectNode = useCallback(
    (nodeId: string) => {
      const node = graph.data?.nodes.find((n) => n.id === nodeId);
      if (node) {
        setSelectedNode(node);
      }
    },
    [graph.data],
  );

  const handleFocusDirectory = useCallback(
    (dir: string) => {
      setFile(dir);
      setSelectedNode(null);
      graph.mutate({ file: dir, depth });
    },
    [depth, graph],
  );

  const nodeCount = graph.data?.nodes.length ?? 0;
  const edgeCount = graph.data?.edges.length ?? 0;

  return (
    <div className="space-y-4">
      <div className="flex items-end gap-3">
        <div className="flex-1">
          <GraphControls
            file={file}
            depth={depth}
            onFileChange={setFile}
            onDepthChange={setDepth}
            onGenerate={handleGenerate}
            loading={graph.isPending}
            layoutMode={layoutMode}
            onLayoutModeChange={setLayoutMode}
            searchQuery={graphSearch}
            onSearchChange={setGraphSearch}
            nodeCount={nodeCount}
            edgeCount={edgeCount}
          />
        </div>
        <div className="flex gap-2">
          {layoutMode === "dagre" && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setDirection((d) => (d === "LR" ? "TB" : "LR"))}
              title={`Layout: ${direction === "LR" ? "Left to Right" : "Top to Bottom"}`}
            >
              {direction === "LR" ? (
                <ArrowRight className="h-4 w-4" />
              ) : (
                <ArrowDown className="h-4 w-4" />
              )}
              {direction}
            </Button>
          )}
          <Button
            variant={showCommunities ? "default" : "outline"}
            size="sm"
            onClick={() => setShowCommunities((v) => !v)}
            title="Toggle community detection overlay"
          >
            <Layers className="h-4 w-4" />
            Communities
          </Button>
        </div>
      </div>

      {graph.isPending && <LoadingSpinner />}

      {graph.data && graph.data.nodes.length > 0 ? (
        <div
          className="relative h-[calc(100vh-20rem)] rounded-lg border border-border overflow-hidden"
          style={{
            background:
              "radial-gradient(ellipse at center, #1a1a2e 0%, #0f0f17 70%)",
          }}
          onClick={(e) => {
            // Close card when clicking background (not bubbled from card/node)
            if (e.target === e.currentTarget) setSelectedNode(null);
          }}
        >
          <DependencyGraph
            nodes={graph.data.nodes}
            edges={graph.data.edges}
            layoutMode={layoutMode}
            direction={direction}
            onNodeSelect={handleNodeSelect}
            selectedNodeId={selectedNode?.id}
            searchQuery={debouncedGraphSearch || undefined}
            communityColorMap={communityColorMap()}
          />
          <NodeInfoCard
            node={selectedNode}
            position={selectedNodePos}
            edges={graph.data.edges}
            onClose={() => setSelectedNode(null)}
            onNavigateToFile={handleNavigateToFile}
            onSelectNode={handleSelectNode}
            onFocusDirectory={handleFocusDirectory}
          />
        </div>
      ) : (
        !graph.isPending && (
          <EmptyState
            icon={<Network className="h-12 w-12" />}
            title="Dependency Graph"
            description={
              graph.data
                ? "No dependencies found. Try reindexing the repository."
                : "Select a directory or file to explore dependencies"
            }
          />
        )
      )}

      {/* Community Detection Info Panel */}
      {showCommunities && communities.data && (
        <div className="mt-4 space-y-3">
          <div className="flex items-center gap-3">
            <h3 className="text-sm font-semibold">Community Detection</h3>
            <Badge variant="secondary">
              {communities.data.method}
            </Badge>
            <span className="text-xs text-muted-foreground">
              Modularity: {communities.data.modularity.toFixed(3)}
            </span>
            <span className="text-xs text-muted-foreground">
              {communities.data.communities.length} communities
            </span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
            {communities.data.communities.map((c, i) => (
              <div
                key={c.id}
                className="rounded-lg border border-border bg-card p-3 space-y-1"
              >
                <div className="flex items-center gap-2">
                  <span
                    className="inline-block h-3 w-3 rounded-full"
                    style={{ backgroundColor: COMMUNITY_COLORS[i % COMMUNITY_COLORS.length] }}
                  />
                  <span className="text-xs font-medium truncate">{c.theme || `Community ${c.id}`}</span>
                  <Badge variant="outline" className="ml-auto text-[10px]">{c.size} files</Badge>
                </div>
                <p className="text-[10px] text-muted-foreground">
                  Hub: <span className="font-mono">{c.hub}</span>
                </p>
                <p className="text-[10px] text-muted-foreground">
                  Cohesion: {c.internal_edges + c.external_edges > 0
                    ? ((c.internal_edges / (c.internal_edges + c.external_edges)) * 100).toFixed(0)
                    : 0}%
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
