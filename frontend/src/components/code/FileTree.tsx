import { useState } from "react";
import { ChevronRight, File, Folder, FolderOpen } from "lucide-react";
import { cn } from "@/lib/cn";
import { getLanguageFromPath, getLanguageColor } from "@/lib/languages";
import type { FileTreeNode } from "@/api/generated/schema";

interface FileTreeProps {
  nodes: FileTreeNode[];
  onSelect: (path: string) => void;
  onSelectDirectory?: (path: string) => void;
  selectedPath?: string;
  depth?: number;
}

export function FileTree({
  nodes,
  onSelect,
  onSelectDirectory,
  selectedPath,
  depth = 0,
}: FileTreeProps) {
  return (
    <div className="text-sm">
      {nodes.map((node) => (
        <TreeNode
          key={node.path}
          node={node}
          onSelect={onSelect}
          onSelectDirectory={onSelectDirectory}
          selectedPath={selectedPath}
          depth={depth}
        />
      ))}
    </div>
  );
}

function TreeNode({
  node,
  onSelect,
  onSelectDirectory,
  selectedPath,
  depth,
}: {
  node: FileTreeNode;
  onSelect: (path: string) => void;
  onSelectDirectory?: (path: string) => void;
  selectedPath?: string;
  depth: number;
}) {
  const [expanded, setExpanded] = useState(depth < 1);
  const isDir = node.type === "directory";
  const isSelected = node.path === selectedPath;
  const lang = !isDir ? getLanguageFromPath(node.path) : undefined;

  return (
    <div>
      <button
        onClick={() => {
          if (isDir) {
            setExpanded(!expanded);
            onSelectDirectory?.(node.path);
          } else {
            onSelect(node.path);
          }
        }}
        className={cn(
          "flex w-full items-center gap-1 rounded px-2 py-1 text-left hover:bg-white/[0.04] transition-colors",
          isSelected && "bg-primary/[0.08] text-foreground",
        )}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
      >
        {isDir ? (
          <>
            <ChevronRight
              className={cn(
                "h-3.5 w-3.5 shrink-0 transition-transform",
                expanded && "rotate-90",
              )}
            />
            {expanded ? (
              <FolderOpen className="h-4 w-4 shrink-0 text-primary/70" />
            ) : (
              <Folder className="h-4 w-4 shrink-0 text-primary/70" />
            )}
          </>
        ) : (
          <>
            <span className="w-3.5" />
            <File className="h-4 w-4 shrink-0 text-muted-foreground" />
          </>
        )}
        <span className="truncate">{node.name}</span>
        {lang && (
          <span
            className="ml-auto h-2 w-2 shrink-0 rounded-full"
            style={{ backgroundColor: getLanguageColor(lang) }}
          />
        )}
      </button>
      {isDir && expanded && node.children && (
        <FileTree
          nodes={node.children}
          onSelect={onSelect}
          onSelectDirectory={onSelectDirectory}
          selectedPath={selectedPath}
          depth={depth + 1}
        />
      )}
    </div>
  );
}
