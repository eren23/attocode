import { type FormEvent } from "react";
import { Input } from "@/components/ui/input";
import { Search, Filter } from "lucide-react";

interface SearchBarProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit?: () => void;
  fileFilter?: string;
  onFileFilterChange?: (value: string) => void;
}

export function SearchBar({ value, onChange, onSubmit, fileFilter, onFileFilterChange }: SearchBarProps) {
  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    onSubmit?.();
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-2">
      <div className="relative flex-1">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="Search code, symbols, or concepts..."
          className="pl-9"
        />
      </div>
      {onFileFilterChange && (
        <div className="relative flex-1">
          <Filter className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={fileFilter ?? ""}
            onChange={(e) => onFileFilterChange(e.target.value)}
            placeholder="Filter by file pattern (e.g. *.py, src/**/*.ts)"
            className="pl-9"
          />
        </div>
      )}
    </form>
  );
}
