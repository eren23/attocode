import type { SymbolInfo } from "@/api/generated/schema";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmptyState } from "@/components/shared/EmptyState";
import { Code2 } from "lucide-react";

export function SymbolList({ symbols }: { symbols: SymbolInfo[] }) {
  if (!symbols.length) {
    return (
      <EmptyState
        icon={<Code2 className="h-8 w-8" />}
        title="No symbols found"
        description="Symbols will appear after the repository is indexed"
      />
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Name</TableHead>
          <TableHead>Kind</TableHead>
          <TableHead>File</TableHead>
          <TableHead>Line</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {symbols.map((sym, i) => (
          <TableRow key={i}>
            <TableCell className="font-mono text-sm">{sym.name}</TableCell>
            <TableCell>
              <Badge variant="secondary">{sym.kind}</Badge>
            </TableCell>
            <TableCell className="text-muted-foreground text-xs truncate max-w-xs">
              {sym.file}
            </TableCell>
            <TableCell className="text-muted-foreground">{sym.line}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
