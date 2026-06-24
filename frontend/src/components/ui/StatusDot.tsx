import { cn } from "@/lib/cn";

type Variant = "critical" | "high" | "medium" | "low" | "info" | "ok";

const COLOR: Record<Variant, string> = {
  critical: "var(--alert-critical)",
  high: "var(--accent-light)",
  medium: "var(--alert-medium)",
  low: "var(--alert-low)",
  info: "var(--blue-mid)",
  ok: "var(--alert-success-light)",
};

const GLOW: Record<Variant, string> = {
  critical: "0 0 8px rgba(224, 61, 61, 0.6)",
  high: "0 0 8px rgba(255, 122, 47, 0.6)",
  medium: "0 0 8px rgba(212, 193, 55, 0.5)",
  low: "0 0 8px rgba(74, 127, 196, 0.5)",
  info: "0 0 8px rgba(62, 111, 212, 0.5)",
  ok: "0 0 8px rgba(46, 204, 138, 0.6)",
};

export function StatusDot({
  variant,
  className,
}: {
  variant: Variant;
  className?: string;
}) {
  return (
    <span
      aria-hidden
      className={cn("block h-2 w-2 rounded-full", className)}
      style={{ backgroundColor: COLOR[variant], boxShadow: GLOW[variant] }}
    />
  );
}
