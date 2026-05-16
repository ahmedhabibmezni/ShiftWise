import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

type Crumb = { label: string; to?: string };

/**
 * Page-level header. Lives at the top of every routed page (inside the main
 * column, below the topbar). Provides breadcrumb + title + meta + actions.
 */
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
        <nav
          aria-label="Breadcrumb"
          className="flex items-center gap-2 text-[12px] text-[var(--text-secondary)] font-medium"
        >
          {breadcrumbs.map((c, i) => (
            <span key={i} className="flex items-center gap-2">
              {i > 0 && <span className="text-[var(--text-muted)] opacity-60">/</span>}
              <span
                className={
                  i === breadcrumbs.length - 1
                    ? "text-[var(--text-primary)] font-semibold"
                    : ""
                }
              >
                {c.label}
              </span>
            </span>
          ))}
        </nav>
      )}
      <div className="flex items-end justify-between gap-6 flex-wrap">
        <div className="min-w-0 flex-1">
          {kicker && <div className="kicker mb-2">{kicker}</div>}
          <h1 className="text-[22px] font-bold tracking-[-0.01em] leading-tight text-[var(--text-primary)]">
            {title}
          </h1>
          {description && (
            <p className="mt-2 text-[13px] text-[var(--text-secondary)] max-w-[64ch] leading-relaxed">
              {description}
            </p>
          )}
          {meta && (
            <div className="mt-3 flex items-center gap-4 flex-wrap">{meta}</div>
          )}
        </div>
        {actions && <div className="flex items-center gap-2 flex-wrap">{actions}</div>}
      </div>
    </header>
  );
}
