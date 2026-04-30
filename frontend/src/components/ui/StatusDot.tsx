import { cn } from "@/lib/cn";

type Variant = "critical" | "high" | "medium" | "low" | "info" | "ok";

const COLOR: Record<Variant, string> = {
  critical: "var(--err)",
  high: "var(--signal)",
  medium: "var(--warn)",
  low: "var(--info)",
  info: "var(--info)",
  ok: "var(--ok)",
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
      style={{ backgroundColor: COLOR[variant] }}
    />
  );
}
