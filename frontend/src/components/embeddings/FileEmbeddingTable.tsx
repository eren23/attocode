import type { EmbeddingFileEntry } from "@/api/generated/schema";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatRelativeTime } from "@/lib/format";
import { EmptyState } from "@/components/shared/EmptyState";
import { Database, Search } from "lucide-react";

interface FileEmbeddingTableProps {
  files: EmbeddingFileEntry[];
  totalFiles?: number;
  searchQuery?: string;
  onFindSimilar?: (contentSha: string) => void;
}

export function FileEmbeddingTable({ files, totalFiles, searchQuery, onFindSimilar }: FileEmbeddingTableProps) {
  if (!files.length) {
    if (searchQuery) {
      return (
        <div className="py-12 text-center text-sm text-muted-foreground">
          No files matching &lsquo;{searchQuery}&rsquo;
        </div>
      );
    }
    return (
      <EmptyState
        icon={<Database className="h-8 w-8" />}
        title="No files indexed"
        description="Trigger indexing to create embeddings"
      />
    );
  }

  return (
    <div>
      {searchQuery && totalFiles != null && (
        <p className="mb-3 text-sm text-muted-foreground">
          Showing {files.length} of {totalFiles.toLocaleString()} files
        </p>
      )}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>File</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Chunks</TableHead>
            <TableHead>Last Embedded</TableHead>
            {onFindSimilar && <TableHead>Actions</TableHead>}
          </TableRow>
        </TableHeader>
        <TableBody className="transition-opacity duration-200">
          {files.map((f, i) => (
            <TableRow key={i} className="hover:bg-accent/5 transition-colors duration-150">
              <TableCell className="font-mono text-[13px] tracking-tight truncate max-w-sm">
                {f.file}
              </TableCell>
              <TableCell>
                <Badge variant={f.embedded ? "success" : "secondary"}>
                  {f.embedded ? "embedded" : "pending"}
                </Badge>
              </TableCell>
              <TableCell>{f.chunk_count}</TableCell>
              <TableCell className="text-muted-foreground text-xs">
                {f.last_embedded_at
                  ? formatRelativeTime(f.last_embedded_at)
                  : "-"}
              </TableCell>
              {onFindSimilar && (
                <TableCell>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={!f.embedded}
                    onClick={() => onFindSimilar(f.content_sha)}
                    title="Find similar files"
                  >
                    <Search className="h-3.5 w-3.5" />
                  </Button>
                </TableCell>
              )}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
