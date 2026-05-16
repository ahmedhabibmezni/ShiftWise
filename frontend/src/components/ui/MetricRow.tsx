import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

const EMPHASIS_COLOR: Record<string, string> = {
  ok: "var(--alert-success-light)",
  warn: "var(--alert-high)",
  err: "var(--alert-critical)",
  signal: "var(--accent-light)",
  info: "var(--blue-mid)",
};

export function MetricRow({
  label,
  value,
  hint,
  emphasis,
  mono,
  className,
}: {
  label: ReactNode;
  value: ReactNode;
  hint?: ReactNode;
  emphasis?: "ok" | "warn" | "err" | "signal" | "info";
  /** Render the value in the monospace face — for IPs, UUIDs, hosts, paths. */
  mono?: boolean;
  className?: string;
}) {
  const color = emphasis ? EMPHASIS_COLOR[emphasis] : "var(--text-primary)";
  return (
    <div
      className={cn(
        "flex items-baseline justify-between gap-3 py-2.5 border-b border-[var(--hairline-faint)] last:border-b-0",
        className,
      )}
    >
      <span className="text-[12px] font-medium text-[var(--text-secondary)]">
        {label}
      </span>
      <span className="flex items-baseline gap-2 min-w-0 text-right">
        {hint && (
          <span className="text-[10px] font-bold uppercase tracking-[0.04em] text-[var(--text-muted)]">
            {hint}
          </span>
        )}
        <span
          className={cn(
            "font-bold tabular truncate",
            mono ? "font-mono text-[12px]" : "text-[13px]",
          )}
          style={{ color }}
        >
          {value}
        </span>
      </span>
    </div>
  );
}
