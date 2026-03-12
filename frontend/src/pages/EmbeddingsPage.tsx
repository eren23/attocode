import { useParams } from "react-router";
import {
  useEmbeddingStatus,
  useEmbeddingFiles,
  useTriggerEmbedding,
} from "@/api/hooks/useEmbeddings";
import { EmbeddingStatusCard } from "@/components/embeddings/EmbeddingStatus";
import { FileEmbeddingTable } from "@/components/embeddings/FileEmbeddingTable";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { Button } from "@/components/ui/button";
import { RefreshCw } from "lucide-react";

export function EmbeddingsPage() {
  const { repoId } = useParams();
  const status = useEmbeddingStatus(repoId!);
  const files = useEmbeddingFiles(repoId!);
  const trigger = useTriggerEmbedding(repoId!);

  if (status.isLoading) return <LoadingSpinner />;

  return (
    <div className="space-y-6 max-w-4xl">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Embeddings</h2>
        <Button
          variant="outline"
          size="sm"
          onClick={() => trigger.mutate(undefined)}
          disabled={trigger.isPending}
        >
          <RefreshCw className={`h-4 w-4 ${trigger.isPending ? "animate-spin" : ""}`} />
          {trigger.isPending ? "Indexing..." : "Reindex"}
        </Button>
      </div>

      {status.data && <EmbeddingStatusCard status={status.data} />}

      {files.isLoading ? (
        <LoadingSpinner />
      ) : (
        <FileEmbeddingTable files={files.data?.files ?? []} />
      )}
    </div>
  );
}
