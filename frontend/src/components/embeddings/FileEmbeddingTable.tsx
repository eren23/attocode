import type { EmbeddingFileEntry } from "@/api/generated/schema";
import { Badge } from "@/components/ui/badge";
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
import { Database } from "lucide-react";

export function FileEmbeddingTable({
  files,
}: {
  files: EmbeddingFileEntry[];
}) {
  if (!files.length) {
    return (
      <EmptyState
        icon={<Database className="h-8 w-8" />}
        title="No files indexed"
        description="Trigger indexing to create embeddings"
      />
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>File</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Chunks</TableHead>
          <TableHead>Last Embedded</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {files.map((f, i) => (
          <TableRow key={i}>
            <TableCell className="font-mono text-xs truncate max-w-sm">
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
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
