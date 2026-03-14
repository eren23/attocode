import { useState, useEffect, useMemo } from "react";
import { useParams, useSearchParams, useLocation } from "react-router";
import { useFileTree } from "@/api/hooks/useFiles";
import { useFileContent } from "@/api/hooks/useFiles";
import { useBlame } from "@/api/hooks/useGit";
import { useRelatedFiles } from "@/api/hooks/useGraph";
import { FileTree } from "@/components/code/FileTree";
import { FileViewer } from "@/components/code/FileViewer";
import { BreadcrumbPath } from "@/components/code/BreadcrumbPath";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { EmptyState } from "@/components/shared/EmptyState";
import { formatBytes, formatRelativeTime, shortSha } from "@/lib/format";
import { FolderGit2, GitBranch, Users, FileSearch } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

export function FileBrowserPage() {
  const { orgId, repoId } = useParams();
  const [searchParams] = useSearchParams();
  const location = useLocation();
  const [selectedPath, setSelectedPath] = useState(searchParams.get("path") || "");
  const [highlightLine, setHighlightLine] = useState<number | null>(null);
  const [showBlame, setShowBlame] = useState(false);
  const [showRelated, setShowRelated] = useState(false);

  useEffect(() => {
    const p = searchParams.get("path");
    if (p) setSelectedPath(p);
  }, [searchParams]);

  useEffect(() => {
    const match = location.hash.match(/^#L(\d+)$/);
    if (match?.[1]) setHighlightLine(parseInt(match[1], 10));
    else setHighlightLine(null);
  }, [location.hash]);
  const { data: treeData, isLoading: treeLoading } = useFileTree(
    orgId!,
    repoId!,
  );
  const { data: fileData, isLoading: fileLoading } = useFileContent(
    orgId!,
    repoId!,
    selectedPath,
  );
  const blame = useBlame(orgId!, repoId!, showBlame ? selectedPath : "");
  const related = useRelatedFiles(repoId!, showRelated ? selectedPath : "");

  // Group consecutive blame lines from the same commit into single annotations
  const blameGroups = useMemo(() => {
    if (!blame.data?.entries) return [];
    const entries = blame.data.entries;
    const groups: { sha: string; author: string; date: string; lineStart: number; lineEnd: number }[] = [];
    for (const entry of entries) {
      const last = groups[groups.length - 1];
      if (last && last.sha === entry.sha && last.lineEnd + 1 >= entry.line_start) {
        last.lineEnd = Math.max(last.lineEnd, entry.line_end);
      } else {
        groups.push({
          sha: entry.sha,
          author: entry.author,
          date: entry.date,
          lineStart: entry.line_start,
          lineEnd: entry.line_end,
        });
      }
    }
    return groups;
  }, [blame.data]);

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
              <div className="flex items-center gap-2">
                {fileData && (
                  <span className="text-xs text-muted-foreground">
                    {fileData.lines} lines | {formatBytes(fileData.size)}
                  </span>
                )}
                <Button
                  variant={showBlame ? "secondary" : "ghost"}
                  size="sm"
                  onClick={() => setShowBlame((v) => !v)}
                  title="Toggle blame annotations"
                >
                  <Users className="mr-1 h-3.5 w-3.5" />
                  Blame
                </Button>
                <Button
                  variant={showRelated ? "secondary" : "ghost"}
                  size="sm"
                  onClick={() => setShowRelated((v) => !v)}
                  title="Show related files"
                >
                  <FileSearch className="mr-1 h-3.5 w-3.5" />
                  Related
                </Button>
              </div>
            </div>
            {fileLoading ? (
              <LoadingSpinner />
            ) : fileData ? (
              <div className="flex flex-1 overflow-hidden">
                {/* Blame gutter */}
                {showBlame && (
                  <div className="w-48 shrink-0 overflow-y-auto border-r border-border bg-zinc-900/50 font-mono text-[11px]">
                    {blame.isLoading ? (
                      <div className="flex items-center justify-center p-4">
                        <LoadingSpinner />
                      </div>
                    ) : (
                      blameGroups.map((group) => {
                        const lineCount = group.lineEnd - group.lineStart + 1;
                        return (
                          <div
                            key={`${group.sha}-${group.lineStart}`}
                            className="border-b border-zinc-800 px-2 py-0.5 text-muted-foreground hover:bg-zinc-800/50"
                            style={{ height: `${lineCount * 1.5}rem` }}
                            title={`${group.sha}\n${group.author}\n${group.date}`}
                          >
                            <div className="flex items-start gap-1.5">
                              <span className="font-semibold text-blue-400">
                                {shortSha(group.sha)}
                              </span>
                              <span className="truncate">{group.author}</span>
                            </div>
                            <div className="text-[10px] text-zinc-500">
                              {formatRelativeTime(group.date)}
                            </div>
                          </div>
                        );
                      })
                    )}
                  </div>
                )}

                {/* File content */}
                <div className="flex-1 overflow-auto">
                  <FileViewer content={fileData.content} path={selectedPath} highlightLine={highlightLine} />
                </div>

                {/* Related files panel */}
                {showRelated && (
                  <div className="w-64 shrink-0 overflow-y-auto border-l border-border bg-zinc-900/50">
                    <div className="flex items-center gap-2 border-b border-border px-3 py-2">
                      <GitBranch className="h-3.5 w-3.5 text-muted-foreground" />
                      <span className="text-xs font-medium">Related Files</span>
                    </div>
                    {related.isLoading ? (
                      <div className="flex items-center justify-center p-4">
                        <LoadingSpinner />
                      </div>
                    ) : related.data?.related?.length ? (
                      <ul className="divide-y divide-zinc-800">
                        {related.data.related.map((f) => (
                          <li key={f.path}>
                            <button
                              className="flex w-full items-center justify-between px-3 py-2 text-left text-xs hover:bg-zinc-800/50"
                              onClick={() => {
                                setSelectedPath(f.path);
                                setShowRelated(false);
                              }}
                            >
                              <span className="truncate text-zinc-300">{f.path}</span>
                              <Badge variant="outline" className="ml-2 shrink-0 text-[10px]">
                                {(f.score * 100).toFixed(0)}%
                              </Badge>
                            </button>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="p-3 text-xs text-muted-foreground">
                        No related files found
                      </p>
                    )}
                  </div>
                )}
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
