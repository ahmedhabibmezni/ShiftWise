import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

type Crumb = { label: string; to?: string };

export function PageHeader({
  kicker,
  title,
  description,
  breadcrumbs,
  meta,
  actions,
  className,
}: {
  kicker?: string;
  title: ReactNode;
  description?: ReactNode;
  breadcrumbs?: Crumb[];
  meta?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <header className={cn("flex flex-col gap-3", className)}>
      {breadcrumbs && breadcrumbs.length > 0 && (
        <nav aria-label="Fil d'ariane" className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.06em] text-ink-muted">
          {breadcrumbs.map((c, i) => (
            <span key={i} className="flex items-center gap-2">
              {i > 0 && <span className="text-ink-faint">/</span>}
              <span className={i === breadcrumbs.length - 1 ? "text-ink" : ""}>
                {c.label}
              </span>
            </span>
          ))}
        </nav>
      )}
      <div className="flex items-end justify-between gap-6 flex-wrap">
        <div className="min-w-0 flex-1">
          {kicker && <div className="kicker mb-2">{kicker}</div>}
          <h1 className="text-h1 lowercase leading-none">{title}</h1>
          {description && (
            <p className="mt-2 text-[13px] text-ink-muted max-w-[64ch] leading-relaxed">
              {description}
            </p>
          )}
          {meta && <div className="mt-3 flex items-center gap-4 flex-wrap">{meta}</div>}
        </div>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>
    </header>
  );
}
