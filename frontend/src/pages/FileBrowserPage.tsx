import { useState } from "react";
import { useParams } from "react-router";
import { useFileTree } from "@/api/hooks/useFiles";
import { useFileContent } from "@/api/hooks/useFiles";
import { FileTree } from "@/components/code/FileTree";
import { FileViewer } from "@/components/code/FileViewer";
import { BreadcrumbPath } from "@/components/code/BreadcrumbPath";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { EmptyState } from "@/components/shared/EmptyState";
import { formatBytes } from "@/lib/format";
import { FolderGit2 } from "lucide-react";

export function FileBrowserPage() {
  const { orgId, repoId } = useParams();
  const [selectedPath, setSelectedPath] = useState("");
  const { data: treeData, isLoading: treeLoading } = useFileTree(
    orgId!,
    repoId!,
  );
  const { data: fileData, isLoading: fileLoading } = useFileContent(
    orgId!,
    repoId!,
    selectedPath,
  );

  if (treeLoading) return <LoadingSpinner />;

  return (
    <div className="flex h-[calc(100vh-14rem)] gap-4">
      {/* File Tree Panel */}
      <div className="w-72 shrink-0 overflow-y-auto rounded-lg border border-border bg-card p-2">
        {treeData?.tree ? (
          <FileTree
            nodes={treeData.tree}
            onSelect={setSelectedPath}
            selectedPath={selectedPath}
          />
        ) : (
          <EmptyState
            icon={<FolderGit2 className="h-8 w-8" />}
            title="No files"
            description="Repository may need indexing"
          />
        )}
      </div>

      {/* File Content Panel */}
      <div className="flex-1 overflow-hidden rounded-lg border border-border bg-card">
        {selectedPath ? (
          <div className="flex h-full flex-col">
            <div className="flex items-center justify-between border-b border-border px-4 py-2">
              <BreadcrumbPath path={selectedPath} onNavigate={setSelectedPath} />
              {fileData && (
                <span className="text-xs text-muted-foreground">
                  {fileData.lines} lines | {formatBytes(fileData.size)}
                </span>
              )}
            </div>
            {fileLoading ? (
              <LoadingSpinner />
            ) : fileData ? (
              <div className="flex-1 overflow-auto">
                <FileViewer content={fileData.content} path={selectedPath} />
              </div>
            ) : null}
          </div>
        ) : (
          <EmptyState
            icon={<FolderGit2 className="h-8 w-8" />}
            title="Select a file"
            description="Choose a file from the tree to view its contents"
          />
        )}
      </div>
    </div>
  );
}
