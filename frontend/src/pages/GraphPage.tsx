import { useState } from "react";
import { useParams } from "react-router";
import { useDependencyGraph } from "@/api/hooks/useGraph";
import { DependencyGraph } from "@/components/graph/DependencyGraph";
import { GraphControls } from "@/components/graph/GraphControls";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { EmptyState } from "@/components/shared/EmptyState";
import { Network } from "lucide-react";

export function GraphPage() {
  const { repoId } = useParams();
  const graph = useDependencyGraph(repoId!);
  const [file, setFile] = useState("");
  const [depth, setDepth] = useState(3);

  const handleGenerate = () => {
    graph.mutate({ file: file || undefined, depth });
  };

  return (
    <div className="space-y-4">
      <GraphControls
        file={file}
        depth={depth}
        onFileChange={setFile}
        onDepthChange={setDepth}
        onGenerate={handleGenerate}
        loading={graph.isPending}
      />

      {graph.isPending && <LoadingSpinner />}

      {graph.data ? (
        <div className="h-[calc(100vh-20rem)] rounded-lg border border-border bg-card">
          <DependencyGraph
            nodes={graph.data.nodes}
            edges={graph.data.edges}
          />
        </div>
      ) : (
        !graph.isPending && (
          <EmptyState
            icon={<Network className="h-12 w-12" />}
            title="Dependency Graph"
            description="Enter a file path and click Generate to visualize dependencies"
          />
        )
      )}
    </div>
  );
}
