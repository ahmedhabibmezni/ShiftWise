import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <kbd
      className={cn(
        "inline-flex items-center justify-center min-w-[20px] h-[20px] px-1.5",
        "text-[10px] font-bold tabular",
        "border border-[var(--hairline)] bg-[var(--surface-soft-strong)] text-[var(--text-primary)] rounded-md",
        className,
      )}
    >
      {children}
    </kbd>
  );
}
