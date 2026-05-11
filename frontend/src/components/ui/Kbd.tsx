import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <kbd
      className={cn(
        "inline-flex items-center justify-center min-w-[18px] h-[18px] px-1.5",
        "font-mono text-[10px] font-medium tabular",
        "border border-line-strong bg-bg-inset text-ink rounded-sm",
        "shadow-[inset_0_-1px_0_var(--line)]",
        className,
      )}
    >
      {children}
    </kbd>
  );
}
