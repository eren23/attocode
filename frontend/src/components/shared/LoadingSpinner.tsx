import { cn } from "@/lib/cn";

export function LoadingSpinner({ className }: { className?: string }) {
  return (
    <div className={cn("flex items-center justify-center p-8", className)}>
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-muted border-t-primary shadow-[0_0_8px_rgba(37,99,235,0.2)]" />
    </div>
  );
}
