import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export function MetricRow({
  label,
  value,
  hint,
  emphasis,
  className,
}: {
  label: ReactNode;
  value: ReactNode;
  hint?: ReactNode;
  emphasis?: "ok" | "warn" | "err" | "signal" | "info";
  className?: string;
}) {
  const tone =
    emphasis === "ok"
      ? "text-ok"
      : emphasis === "warn"
        ? "text-warn"
        : emphasis === "err"
          ? "text-err"
          : emphasis === "signal"
            ? "text-signal"
            : emphasis === "info"
              ? "text-info-soft"
              : "text-ink";
  return (
    <div
      className={cn(
        "flex items-baseline justify-between gap-3 py-2 border-b border-line last:border-b-0",
        className,
      )}
    >
      <span className="kicker">{label}</span>
      <span className="flex items-baseline gap-2 min-w-0 text-right">
        {hint && (
          <span className="font-mono text-[10px] text-ink-faint uppercase tracking-[0.06em]">
            {hint}
          </span>
        )}
        <span className={cn("font-mono text-[13px] tabular truncate", tone)}>{value}</span>
      </span>
    </div>
  );
}
