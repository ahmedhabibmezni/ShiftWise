import { cn } from "@/lib/cn";

type Tone = "signal" | "ok" | "warn" | "err";

const COLOR: Record<Tone, string> = {
  signal: "var(--accent-light)",
  ok: "var(--alert-success-light)",
  warn: "var(--alert-high)",
  err: "var(--alert-critical)",
};

export function LiveIndicator({
  label = "Live",
  srLabel,
  tone = "ok",
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
      <span aria-hidden className="relative inline-flex h-2.5 w-2.5">
        <span
          className="absolute inset-0 rounded-full opacity-60"
          style={{
            backgroundColor: color,
            animation: "shiftwise-pulse 1.8s var(--ease-out) infinite",
          }}
        />
        <span
          className="relative inline-flex h-2.5 w-2.5 rounded-full"
          style={{ backgroundColor: color, boxShadow: `0 0 8px ${color}` }}
        />
      </span>
      {hasVisibleLabel && (
        <span className="text-[11px] font-bold uppercase tracking-[0.06em] text-[var(--text-secondary)]">
          {label}
        </span>
      )}
      {accessibleLabel && <span className="sr-only">{accessibleLabel}</span>}
    </span>
  );
}
