import { useState } from "react";
import { useParams } from "react-router";
import {
  useEmbeddingStatus,
  useEmbeddingFiles,
  useTriggerEmbedding,
  useFindSimilar,
} from "@/api/hooks/useEmbeddings";
import { useSearch } from "@/api/hooks/useSearch";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { EmbeddingCoverageInline } from "@/components/embeddings/EmbeddingStatus";
import { EmbeddingSearchPreview } from "@/components/embeddings/EmbeddingSearchPreview";
import { FileEmbeddingTable } from "@/components/embeddings/FileEmbeddingTable";
import { SimilarFilesPanel } from "@/components/embeddings/SimilarFilesPanel";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/api/client";
import { cn } from "@/lib/cn";
import { RefreshCw, Search } from "lucide-react";

type Tab = "Status" | "Search";

export function EmbeddingsPage() {
  const { repoId } = useParams();
  const status = useEmbeddingStatus(repoId!);
  const trigger = useTriggerEmbedding(repoId!);
  const findSimilar = useFindSimilar(repoId!);

  const [tab, setTab] = useState<Tab>("Status");
  const [query, setQuery] = useState("");
  const [pendingOnly, setPendingOnly] = useState(false);
  const debouncedQuery = useDebouncedValue(query, 400);
  const files = useEmbeddingFiles(repoId!, tab === "Status" ? "" : debouncedQuery);
  const statusFiles = useEmbeddingFiles(repoId!, "");
  const search = useSearch(repoId!, debouncedQuery, { topK: 50 });

  const [similarTarget, setSimilarTarget] = useState<{ sha: string; file: string } | null>(null);

  const triggerErrorMessage =
    trigger.error instanceof ApiError
      ? trigger.error.detail
      : trigger.error?.message;

  const handleFindSimilar = (contentSha: string) => {
    const allFiles = (tab === "Status" ? statusFiles : files).data?.files;
    const matchedFile = allFiles?.find((f) => f.content_sha === contentSha);
    setSimilarTarget({ sha: contentSha, file: matchedFile?.file ?? "unknown" });
    findSimilar.mutate(contentSha);
  };

  const handleFindSimilarFromSearch = (filePath: string) => {
    const allFiles = statusFiles.data?.files;
    const matchedFile = allFiles?.find((f) => f.file === filePath);
    if (matchedFile?.content_sha) {
      setSimilarTarget({ sha: matchedFile.content_sha, file: filePath });
      findSimilar.mutate(matchedFile.content_sha);
    }
  };

  const totalFiles = status.data?.total_files ?? 0;

  // Filter files for the Status tab
  const statusFileList = statusFiles.data?.files ?? [];
  const filteredStatusFiles = pendingOnly
    ? statusFileList.filter((f) => !f.embedded)
    : statusFileList;

  if (status.isLoading) return <LoadingSpinner />;

  return (
    <div className="space-y-5 max-w-4xl">
      {/* Compact header bar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <h2 className="text-xl font-semibold">Embeddings</h2>
          {status.data && <EmbeddingCoverageInline status={status.data} />}
        </div>
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

      {triggerErrorMessage && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
          <strong>Reindex failed:</strong> {triggerErrorMessage}
        </div>
      )}

      {status.data?.provider_available === false && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
          <strong>No embedding provider configured.</strong>{" "}
          {status.data.provider_hint || "Install sentence-transformers or set OPENAI_API_KEY."}
        </div>
      )}

      {/* Tab switcher */}
      <div className="border-b border-border">
        <div className="flex gap-0">
          {(["Status", "Search"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={cn(
                "relative px-4 py-2 text-sm font-medium transition-colors",
                tab === t
                  ? "text-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {t}
              {tab === t && (
                <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-violet-500" />
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Status Tab */}
      {tab === "Status" && (
        <>
          {/* Filter toggles */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground">Filter:</span>
            <div className="flex rounded-md border border-border">
              <button
                onClick={() => setPendingOnly(false)}
                className={cn(
                  "px-3 py-1.5 text-xs transition-colors rounded-l-md",
                  !pendingOnly
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                Show all
              </button>
              <button
                onClick={() => setPendingOnly(true)}
                className={cn(
                  "px-3 py-1.5 text-xs transition-colors rounded-r-md",
                  pendingOnly
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                Pending only
              </button>
            </div>
          </div>

          {/* File list */}
          <div
            className={`animate-fade-in ${statusFiles.isFetching ? "opacity-50 transition-opacity" : "transition-opacity"}`}
          >
            {statusFiles.isLoading ? (
              <LoadingSpinner />
            ) : (
              <FileEmbeddingTable
                files={filteredStatusFiles}
                totalFiles={statusFiles.data?.total ?? totalFiles}
                onFindSimilar={handleFindSimilar}
              />
            )}
          </div>

          {/* Similar files panel (status tab) */}
          {findSimilar.isPending && similarTarget && <LoadingSpinner />}
          {findSimilar.data && similarTarget && (
            <SimilarFilesPanel
              sourceFile={findSimilar.data.source_file || similarTarget.file}
              results={findSimilar.data.similar}
              onClose={() => {
                setSimilarTarget(null);
                findSimilar.reset();
              }}
            />
          )}
        </>
      )}

      {/* Search Tab */}
      {tab === "Search" && (
        <>
          {/* Full-width search input */}
          <div className="relative">
            <Search className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={`Search ${totalFiles.toLocaleString()} files semantically...`}
              className="h-12 w-full rounded-lg border border-input bg-background pl-11 pr-4 text-sm transition-all focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-transparent placeholder:text-muted-foreground"
            />
            {debouncedQuery && search.data && (
              <span className="absolute right-3 top-1/2 -translate-y-1/2 rounded-md bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                {search.data.results.length} results
              </span>
            )}
          </div>

          {/* Semantic search results */}
          {search.data && search.data.results.length > 0 && (
            <div className="space-y-3">
              <EmbeddingSearchPreview
                results={search.data.results}
                query={search.data.query}
                total={search.data.total}
                repoId={repoId!}
              />
              {/* Find Similar buttons for each result */}
              <div className="space-y-1">
                {search.data.results.map((result) => (
                  <div
                    key={result.file}
                    className="flex items-center justify-between rounded-md px-3 py-1.5 text-xs hover:bg-accent/50"
                  >
                    <span className="font-mono text-muted-foreground truncate">
                      {result.file}
                    </span>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-xs h-7 shrink-0"
                      onClick={() => handleFindSimilarFromSearch(result.file)}
                    >
                      Find Similar
                    </Button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Similar files panel (search tab) */}
          {findSimilar.isPending && similarTarget && <LoadingSpinner />}
          {findSimilar.data && similarTarget && (
            <SimilarFilesPanel
              sourceFile={findSimilar.data.source_file || similarTarget.file}
              results={findSimilar.data.similar}
              onClose={() => {
                setSimilarTarget(null);
                findSimilar.reset();
              }}
            />
          )}
        </>
      )}
    </div>
  );
}
