import type { LucideIcon } from "lucide-react";
import { ArrowDown, ArrowUp } from "lucide-react";
import { Icon } from "./Icon";
import { cn } from "@/lib/cn";

/**
 * Compact stat block — used inside hero panels and chart panels for sub-stats.
 * Provides icon + label + display value + optional delta line.
 */
export function StatBlock({
  icon,
  label,
  value,
  delta,
  deltaUnit = "vs 24h",
  inkColor,
  className,
}: {
  icon: LucideIcon;
  label: string;
  value: string;
  delta?: { dir: "up" | "down"; value: string; tone: "ok" | "err" };
  deltaUnit?: string;
  inkColor?: string;
  className?: string;
}) {
  const c = inkColor ?? "var(--text-primary)";
  const deltaColor =
    delta?.tone === "ok"
      ? "var(--alert-success-light)"
      : delta?.tone === "err"
        ? "var(--alert-critical)"
        : "currentColor";

  return (
    <div className={cn("flex flex-col gap-2", className)} style={{ color: c }}>
      <div className="flex items-center gap-2">
        <Icon icon={icon} size={16} />
        <span className="text-[12px] font-bold uppercase tracking-[0.04em] opacity-80">
          {label}
        </span>
      </div>
      <div
        className="text-[28px] font-bold tabular leading-none tracking-[-0.02em]"
        style={{ color: c }}
      >
        {value}
      </div>
      {delta && (
        <div className="flex items-center gap-1.5 mt-1">
          <Icon
            icon={delta.dir === "up" ? ArrowUp : ArrowDown}
            size={12}
            strokeWidth={2.25}
            style={{ color: deltaColor }}
          />
          <span className="text-[12px] font-bold tabular" style={{ color: deltaColor }}>
            {delta.value}
          </span>
          <span className="text-[11px] opacity-80">{deltaUnit}</span>
        </div>
      )}
    </div>
  );
}
