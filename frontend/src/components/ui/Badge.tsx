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
  | "low"
  | "run";

const TONES: Record<BadgeVariant, { bg: string; fg: string }> = {
  ok:           { bg: "rgba(1, 181, 116, 0.18)",  fg: "var(--alert-success-light)" },
  partial:      { bg: "rgba(232, 146, 42, 0.18)", fg: "var(--alert-high)" },
  incompatible: { bg: "rgba(224, 61, 61, 0.18)",  fg: "var(--alert-critical)" },
  info:         { bg: "rgba(62, 111, 212, 0.18)", fg: "var(--blue-mid)" },
  warn:         { bg: "rgba(232, 146, 42, 0.18)", fg: "var(--alert-high)" },
  neutral:      { bg: "var(--surface-soft-strong)", fg: "var(--text-muted)" },
  critical:     { bg: "rgba(224, 61, 61, 0.18)",  fg: "var(--alert-critical)" },
  high:         { bg: "rgba(230, 38, 0, 0.18)",   fg: "var(--accent-light)" },
  medium:       { bg: "rgba(212, 193, 55, 0.18)", fg: "var(--alert-medium)" },
  low:          { bg: "rgba(74, 127, 196, 0.18)", fg: "var(--alert-low)" },
  run:          { bg: "rgba(230, 38, 0, 0.18)",   fg: "var(--accent-light)" },
};

/**
 * Uppercase micro pill — the canonical ShiftWise status chip.
 * Renders as a `.status-chip` from base.css with tone-specific colours.
 */
export function Badge({
  variant = "neutral",
  children,
  dot = false,
  className,
}: {
  variant?: BadgeVariant;
  children: ReactNode;
  dot?: boolean;
  className?: string;
}) {
  const tone = TONES[variant];
  return (
    <span
      className={cn("status-chip tabular", className)}
      style={{ background: tone.bg, color: tone.fg }}
    >
      {dot && (
        <span
          aria-hidden
          className="block h-1.5 w-1.5 rounded-full"
          style={{ background: tone.fg }}
        />
      )}
      {children}
    </span>
  );
}
