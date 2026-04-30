import { cn } from "@/lib/cn";

export function ProgressBar({
  value,
  showPct,
  variant = "signal",
  trackColor,
  className,
}: {
  value: number;
  showPct?: boolean;
  variant?: "signal" | "ok" | "white";
  trackColor?: string;
  className?: string;
}) {
  const v = Math.max(0, Math.min(100, value));
  const fill =
    variant === "white"
      ? "rgba(255,255,255,0.95)"
      : variant === "ok"
        ? "var(--ok)"
        : "var(--signal)";
  const track =
    trackColor ??
    (variant === "white"
      ? "rgba(255,255,255,0.25)"
      : `color-mix(in srgb, ${fill} 20%, transparent)`);

  return (
    <div className={cn("flex items-center gap-3", className)}>
      <div
        className="relative h-1 flex-1"
        style={{ backgroundColor: track }}
        role="progressbar"
        aria-valuenow={v}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className="absolute inset-y-0 left-0 transition-[width] duration-150"
          style={{ width: `${v}%`, backgroundColor: fill }}
        />
      </div>
      {showPct && (
        <span
          className="font-mono text-[12px] tabular w-10 text-right"
          style={{ color: variant === "white" ? "rgba(255,255,255,0.95)" : "var(--ink-muted)" }}
        >
          {v}%
        </span>
      )}
    </div>
  );
}
