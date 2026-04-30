import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export type BadgeVariant =
  | "ok"
  | "partial"
  | "incompatible"
  | "info"
  | "warn"
  | "neutral"
  | "critical"
  | "high"
  | "medium"
  | "low";

const COLOR: Record<BadgeVariant, string> = {
  ok: "var(--ok)",
  partial: "var(--warn)",
  incompatible: "var(--err)",
  info: "var(--info)",
  warn: "var(--warn)",
  neutral: "var(--ink-muted)",
  critical: "var(--err)",
  high: "var(--signal)",
  medium: "var(--warn)",
  low: "var(--info)",
};

export function Badge({
  variant = "neutral",
  children,
  dot = true,
  className,
}: {
  variant?: BadgeVariant;
  children: ReactNode;
  dot?: boolean;
  className?: string;
}) {
  const c = COLOR[variant];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-sm border px-2 py-0.5",
        "font-mono uppercase text-[11px] font-medium tracking-[0.04em] tabular",
        className,
      )}
      style={{
        color: c,
        borderColor: "transparent",
        backgroundColor: `color-mix(in srgb, ${c} calc(var(--tint-pct) * 100%), transparent)`,
      }}
    >
      {dot && (
        <span
          aria-hidden
          className="block h-1.5 w-1.5"
          style={{ backgroundColor: c }}
        />
      )}
      {children}
    </span>
  );
}
