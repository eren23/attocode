import { ChevronRight } from "lucide-react";

interface BreadcrumbPathProps {
  path: string;
  onNavigate: (path: string) => void;
}

export function BreadcrumbPath({ path, onNavigate }: BreadcrumbPathProps) {
  const parts = path.split("/").filter(Boolean);

  return (
    <nav className="flex items-center gap-1 text-sm">
      <button
        onClick={() => onNavigate("")}
        className="text-muted-foreground hover:text-foreground transition-colors"
      >
        root
      </button>
      {parts.map((part, i) => {
        const partPath = parts.slice(0, i + 1).join("/");
        const isLast = i === parts.length - 1;
        return (
          <span key={partPath} className="flex items-center gap-1">
            <ChevronRight className="h-3 w-3 text-muted-foreground" />
            <button
              onClick={() => onNavigate(partPath)}
              className={
                isLast
                  ? "font-medium text-foreground"
                  : "text-muted-foreground hover:text-foreground transition-colors"
              }
            >
              {part}
            </button>
          </span>
        );
      })}
    </nav>
  );
}
