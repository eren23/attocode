import type { HTMLAttributes } from "react";
import { cn } from "@/lib/cn";

const variants = {
  default: "bg-primary/15 text-primary border-primary/20",
  secondary: "bg-secondary text-secondary-foreground border-secondary",
  destructive: "bg-destructive/15 text-destructive border-destructive/20",
  outline: "text-foreground border-border",
  success: "bg-success/15 text-success border-success/20",
  warning: "bg-warning/15 text-warning border-warning/20",
} as const;

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: keyof typeof variants;
}

export function Badge({
  className,
  variant = "default",
  ...props
}: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium transition-colors",
        variants[variant],
        className,
      )}
      {...props}
    />
  );
}
