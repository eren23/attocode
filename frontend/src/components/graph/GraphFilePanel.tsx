import { useFileContent } from "@/api/hooks/useFiles";
import { Button } from "@/components/ui/button";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { X, ExternalLink } from "lucide-react";

interface GraphFilePanelProps {
  orgId: string;
  repoId: string;
  filePath: string;
  onClose: () => void;
  onNavigateToFile: (path: string) => void;
}

export function GraphFilePanel({
  orgId,
  repoId,
  filePath,
  onClose,
  onNavigateToFile,
}: GraphFilePanelProps) {
  const file = useFileContent(orgId, repoId, filePath);

  return (
    <div className="w-[450px] shrink-0 flex flex-col border-l border-border bg-[--color-surface-1] rounded-r-lg overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
        <div className="min-w-0 flex-1">
          <p className="truncate font-mono text-xs text-foreground">{filePath}</p>
        </div>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            className="h-7 w-7 p-0"
            onClick={() => onNavigateToFile(filePath)}
            title="Open in full page"
          >
            <ExternalLink className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 w-7 p-0"
            onClick={onClose}
            title="Close panel"
          >
            <X className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto">
        {file.isLoading && (
          <div className="flex items-center justify-center p-8">
            <LoadingSpinner />
          </div>
        )}
        {file.isError && (
          <div className="p-4 text-sm text-red-400">
            Failed to load file content.
          </div>
        )}
        {file.data && (
          <pre className="p-3 text-xs leading-relaxed font-mono text-muted-foreground overflow-x-auto">
            <code>
              {file.data.content.split("\n").map((line, i) => (
                <div key={i} className="flex hover:bg-white/[0.02]">
                  <span className="inline-block w-10 shrink-0 text-right pr-3 select-none text-muted-foreground/40">
                    {i + 1}
                  </span>
                  <span className="flex-1 whitespace-pre">{line}</span>
                </div>
              ))}
            </code>
          </pre>
        )}
      </div>
    </div>
  );
}
