import { cn } from "@/lib/cn";

type Variant = "signal" | "ok" | "warn" | "err" | "blue" | "white";

const FILL: Record<Variant, string> = {
  signal: "linear-gradient(90deg, var(--accent-primary), var(--accent-light))",
  ok:     "linear-gradient(90deg, var(--alert-success), var(--alert-success-light))",
  warn:   "linear-gradient(90deg, var(--alert-high), #F4B870)",
  err:    "linear-gradient(90deg, var(--alert-critical), #F47373)",
  blue:   "linear-gradient(90deg, var(--blue-deep), var(--blue-mid))",
  white:  "rgba(255,255,255,0.95)",
};

export function ProgressBar({
  value,
  showPct,
  variant = "signal",
  trackColor,
  height = 4,
  className,
}: {
  value: number;
  showPct?: boolean;
  variant?: Variant;
  trackColor?: string;
  height?: number;
  className?: string;
}) {
  const v = Math.max(0, Math.min(100, value));
  const fill = FILL[variant];
  const track =
    trackColor ??
    (variant === "white" ? "rgba(255,255,255,0.25)" : "var(--surface-soft-strong)");

  return (
    <div className={cn("flex items-center gap-3", className)}>
      <div
        className="relative flex-1 rounded-full overflow-hidden"
        style={{ backgroundColor: track, height }}
        role="progressbar"
        aria-valuenow={v}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className="absolute inset-y-0 left-0 rounded-full transition-[width] duration-300"
          style={{ width: `${v}%`, background: fill }}
        />
      </div>
      {showPct && (
        <span
          className="text-[12px] font-bold tabular w-10 text-right"
          style={{
            color:
              variant === "white" ? "rgba(255,255,255,0.95)" : "var(--text-primary)",
          }}
        >
          {Number(v.toFixed(2))}%
        </span>
      )}
    </div>
  );
}
