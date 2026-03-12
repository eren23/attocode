import type { HotspotEntry } from "@/api/generated/schema";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmptyState } from "@/components/shared/EmptyState";
import { Flame } from "lucide-react";

export function HotspotsTable({ hotspots }: { hotspots: HotspotEntry[] }) {
  if (!hotspots.length) {
    return (
      <EmptyState
        icon={<Flame className="h-8 w-8" />}
        title="No hotspots found"
      />
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>File</TableHead>
          <TableHead>Score</TableHead>
          <TableHead>Commits</TableHead>
          <TableHead>Complexity</TableHead>
          <TableHead>Lines</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {hotspots.map((h, i) => (
          <TableRow key={i}>
            <TableCell className="font-mono text-xs truncate max-w-sm">
              {h.file}
            </TableCell>
            <TableCell>
              <div className="flex items-center gap-2">
                <div className="h-2 w-16 rounded-full bg-zinc-800">
                  <div
                    className="h-2 rounded-full bg-amber-500"
                    style={{ width: `${Math.min(h.score * 100, 100)}%` }}
                  />
                </div>
                <span className="text-xs">{(h.score * 100).toFixed(0)}%</span>
              </div>
            </TableCell>
            <TableCell>{h.commit_count}</TableCell>
            <TableCell>{h.complexity}</TableCell>
            <TableCell>{h.lines}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
