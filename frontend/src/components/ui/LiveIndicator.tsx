import { cn } from "@/lib/cn";

type Tone = "signal" | "ok" | "warn" | "err";

const COLOR: Record<Tone, string> = {
  signal: "var(--signal)",
  ok: "var(--ok)",
  warn: "var(--warn)",
  err: "var(--err)",
};

export function LiveIndicator({
  label = "live",
  srLabel,
  tone = "signal",
  className,
}: {
  label?: string | null;
  srLabel?: string;
  tone?: Tone;
  className?: string;
}) {
  const color = COLOR[tone];
  const hasVisibleLabel = label !== null && label !== "";
  const accessibleLabel = hasVisibleLabel ? undefined : (srLabel ?? null);
  return (
    <span
      className={cn("inline-flex items-center gap-2", className)}
      role={accessibleLabel ? "status" : undefined}
    >
      <span
        aria-hidden
        className="relative inline-flex h-2.5 w-2.5"
      >
        <span
          className="absolute inset-0 rounded-full opacity-60"
          style={{
            backgroundColor: color,
            animation: "shiftwise-pulse 1.8s var(--ease-out) infinite",
          }}
        />
        <span
          className="relative inline-flex h-2.5 w-2.5 rounded-full"
          style={{ backgroundColor: color }}
        />
      </span>
      {hasVisibleLabel && (
        <span className="font-mono text-[11px] uppercase tracking-[0.06em] text-ink-muted">
          {label}
        </span>
      )}
      {accessibleLabel && <span className="sr-only">{accessibleLabel}</span>}
    </span>
  );
}
