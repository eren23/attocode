import type { HTMLAttributes } from "react";
import { cn } from "@/lib/cn";

const variants = {
  default: "bg-primary/15 text-primary border-primary/20 shadow-[0_0_6px_rgba(37,99,235,0.08)]",
  secondary: "bg-secondary text-secondary-foreground border-secondary",
  destructive: "bg-destructive/15 text-destructive border-destructive/20 shadow-[0_0_6px_rgba(220,38,38,0.08)]",
  outline: "text-foreground border-border",
  success: "bg-success/15 text-success border-success/20 shadow-[0_0_6px_rgba(16,185,129,0.08)]",
  warning: "bg-warning/15 text-warning border-warning/20 shadow-[0_0_6px_rgba(245,158,11,0.08)]",
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
