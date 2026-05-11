import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

type Tone = "default" | "elevated" | "inset" | "signal" | "info";
type Density = "comfortable" | "compact";

const TONES: Record<Tone, string> = {
  default: "bg-bg-elev border border-line",
  elevated: "bg-bg-elev border border-line shadow-[var(--shadow-elev)]",
  inset: "bg-bg-inset border border-line",
  signal: "bg-signal text-signal-ink border border-transparent",
  info: "bg-info text-info-ink border border-transparent",
};

export function Panel({
  kicker,
  title,
  hint,
  action,
  footer,
  tone = "default",
  density = "comfortable",
  className,
  bodyClassName,
  children,
  interactive,
  onClick,
  asSection = true,
}: {
  kicker?: string;
  title?: ReactNode;
  hint?: ReactNode;
  action?: ReactNode;
  footer?: ReactNode;
  tone?: Tone;
  density?: Density;
  className?: string;
  bodyClassName?: string;
  children?: ReactNode;
  interactive?: boolean;
  onClick?: () => void;
  asSection?: boolean;
}) {
  const Tag = asSection ? "section" : "div";
  const hasHeader = !!(kicker || title || action);
  return (
    <Tag
      onClick={onClick}
      className={cn(
        "relative flex flex-col rounded-sm overflow-hidden",
        TONES[tone],
        interactive &&
          "cursor-pointer transition-[box-shadow,border-color,transform] duration-200 hover:shadow-[var(--shadow-hover)] hover:border-line-strong",
        className,
      )}
    >
      {hasHeader && (
        <header
          className={cn(
            "flex items-start justify-between gap-3",
            density === "compact" ? "px-4 pt-3 pb-2" : "px-6 pt-5 pb-3",
          )}
        >
          <div className="min-w-0 flex-1">
            {kicker && <div className="kicker mb-1.5">{kicker}</div>}
            {title && (
              <h3
                className={cn(
                  "lowercase leading-tight truncate",
                  density === "compact" ? "text-h3" : "text-h2",
                )}
              >
                {title}
              </h3>
            )}
            {hint && (
              <div className="mt-1 font-mono text-[11px] text-ink-muted lowercase">
                {hint}
              </div>
            )}
          </div>
          {action && <div className="shrink-0 flex items-center gap-2">{action}</div>}
        </header>
      )}
      <div
        className={cn(
          density === "compact" ? "px-4 pb-3" : "px-6 pb-5",
          !hasHeader && (density === "compact" ? "pt-3" : "pt-5"),
          "flex-1",
          bodyClassName,
        )}
      >
        {children}
      </div>
      {footer && (
        <footer
          className={cn(
            "border-t border-line bg-bg-inset/60",
            density === "compact" ? "px-4 py-2" : "px-6 py-3",
          )}
        >
          {footer}
        </footer>
      )}
    </Tag>
  );
}
