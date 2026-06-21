import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

type IconTone = "accent" | "blue" | "success" | "warn" | "muted";

const ICON_CLASS: Record<IconTone, string> = {
  accent:  "icon-container icon-container--accent",
  blue:    "icon-container icon-container--blue",
  success: "icon-container icon-container--success",
  warn:    "icon-container icon-container--warn",
  muted:   "icon-container icon-container--muted",
};

/**
 * KPI card — the canonical Vision UI metric tile.
 *
 *   ┌────────────────────────────────────┐
 *   │  Label              ┌──────────┐   │
 *   │  12,847 +8%         │  icon    │   │
 *   └────────────────────────────────────┘
 *
 * Wraps a glass card and adds a 45×45 gradient icon container.
 */
export function KPIPrimary({
  label,
  value,
  delta,
  deltaTone = "up",
  icon: IconComponent,
  iconTone = "accent",
  className,
  href,
  onClick,
  children,
}: {
  label: string;
  value: ReactNode;
  delta?: ReactNode;
  deltaTone?: "up" | "down" | "neutral";
  icon: LucideIcon;
  iconTone?: IconTone;
  className?: string;
  href?: string;
  onClick?: () => void;
  children?: ReactNode;
}) {
  const Tag = href ? "a" : onClick ? "button" : "div";
  const props: Record<string, unknown> = href
    ? { href }
    : onClick
      ? { type: "button", onClick }
      : {};

  return (
    <Tag
      {...props}
      className={cn(
        "glass-card text-left p-[22px] block w-full",
        (href || onClick) && "transition-transform duration-200",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0 flex flex-col gap-0.5">
          <div className="text-[12px] font-medium text-[var(--text-secondary)]">
            {label}
          </div>
          {/* Reserve the kpi line-box height so the loading skeleton and the
              resolved value occupy the same vertical space — no layout shift
              when data arrives, regardless of the skeleton's own height. */}
          <div className="flex items-baseline gap-2 mt-0.5 min-h-[34px]">
            <span className="text-kpi text-[var(--text-primary)] tabular leading-none">
              {value}
            </span>
            {delta && (
              <span
                className="text-[12px] font-bold tabular leading-none"
                style={{
                  color:
                    deltaTone === "down"
                      ? "var(--alert-critical)"
                      : deltaTone === "neutral"
                        ? "var(--text-muted)"
                        : "var(--alert-success-light)",
                }}
              >
                {delta}
              </span>
            )}
          </div>
        </div>
        <span
          aria-hidden
          className={cn(ICON_CLASS[iconTone], "w-[45px] h-[45px] rounded-xl shrink-0")}
        >
          <IconComponent size={20} strokeWidth={1.75} />
        </span>
      </div>
      {children && <div className="mt-4">{children}</div>}
    </Tag>
  );
}
