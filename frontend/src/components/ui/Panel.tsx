import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

type Props = {
  label: string;
  meta?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
};

export function Panel({ label, meta, children, className, bodyClassName }: Props) {
  return (
    <section className={cn("border border-line bg-bg", className)}>
      <header className="flex items-center justify-between border-b border-line h-7 px-3">
        <span className="font-mono text-[11px] uppercase tracking-[0.05em] text-ink">
          {label}
        </span>
        {meta != null && (
          <span className="font-mono text-[11px] uppercase tracking-[0.05em] text-ink-muted">
            {meta}
          </span>
        )}
      </header>
      <div className={cn("p-4", bodyClassName)}>{children}</div>
    </section>
  );
}
