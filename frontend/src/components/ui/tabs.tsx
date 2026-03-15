import { useRef, type KeyboardEvent } from "react";
import { cn } from "@/lib/cn";

interface TabGroupProps<T extends string> {
  items: readonly T[];
  value: T;
  onChange: (value: T) => void;
  className?: string;
}

export function TabGroup<T extends string>({
  items,
  value,
  onChange,
  className,
}: TabGroupProps<T>) {
  const tabsRef = useRef<(HTMLButtonElement | null)[]>([]);

  const handleKeyDown = (e: KeyboardEvent, index: number) => {
    let next = index;
    if (e.key === "ArrowRight") {
      next = (index + 1) % items.length;
    } else if (e.key === "ArrowLeft") {
      next = (index - 1 + items.length) % items.length;
    } else if (e.key === "Home") {
      next = 0;
    } else if (e.key === "End") {
      next = items.length - 1;
    } else {
      return;
    }
    e.preventDefault();
    tabsRef.current[next]?.focus();
    onChange(items[next]!);
  };

  return (
    <div
      role="tablist"
      className={cn(
        "inline-flex rounded-lg bg-[--color-surface-1]/60 p-1 border border-border/30",
        className,
      )}
    >
      {items.map((item, i) => (
        <button
          key={item}
          ref={(el) => { tabsRef.current[i] = el; }}
          role="tab"
          aria-selected={item === value}
          tabIndex={item === value ? 0 : -1}
          onClick={() => onChange(item)}
          onKeyDown={(e) => handleKeyDown(e, i)}
          className={cn(
            "px-4 py-2 text-sm transition-all rounded-md",
            item === value
              ? "bg-[--color-surface-3] text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {item}
        </button>
      ))}
    </div>
  );
}
