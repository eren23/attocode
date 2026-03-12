import { Button } from "@/components/ui/button";
import { ChevronLeft, ChevronRight } from "lucide-react";

interface PaginationProps {
  total: number;
  limit: number;
  offset: number;
  onPageChange: (offset: number) => void;
}

export function Pagination({
  total,
  limit,
  offset,
  onPageChange,
}: PaginationProps) {
  const currentPage = Math.floor(offset / limit) + 1;
  const totalPages = Math.ceil(total / limit);

  if (totalPages <= 1) return null;

  return (
    <div className="flex items-center justify-between px-2 py-3">
      <span className="text-sm text-muted-foreground">
        {offset + 1}-{Math.min(offset + limit, total)} of {total}
      </span>
      <div className="flex items-center gap-1">
        <Button
          variant="outline"
          size="icon"
          disabled={offset === 0}
          onClick={() => onPageChange(Math.max(0, offset - limit))}
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <span className="px-3 text-sm">
          {currentPage} / {totalPages}
        </span>
        <Button
          variant="outline"
          size="icon"
          disabled={offset + limit >= total}
          onClick={() => onPageChange(offset + limit)}
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
