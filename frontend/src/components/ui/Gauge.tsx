import { useId } from "react";
import { cn } from "@/lib/cn";
import { useCountUp } from "@/hooks/useCountUp";

const TONE_GRAD: Record<string, [string, string]> = {
  signal:  ["var(--accent-primary)", "var(--accent-light)"],
  ok:      ["var(--alert-success)", "var(--alert-success-light)"],
  warn:    ["#C97718", "var(--alert-high)"],
  err:     ["var(--alert-critical)", "#F47373"],
  info:    ["var(--blue-deep)", "var(--blue-mid)"],
};

export function Gauge({
  value,
  max = 100,
  size = 130,
  thickness = 8,
  label,
  sublabel,
  tone = "ok",
  className,
}: {
  value: number;
  max?: number;
  size?: number;
  thickness?: number;
  label?: string;
  sublabel?: string;
  tone?: "ok" | "warn" | "err" | "signal" | "info";
  className?: string;
}) {
  const id = useId().replace(/[:]/g, "");
  // Centre readout counts up in step with the arc's stroke-dasharray tween.
  const displayValue = useCountUp(value);
  const pct = Math.max(0, Math.min(1, value / max));
  const radius = (size - thickness) / 2;
  const circumference = 2 * Math.PI * radius;
  const dash = pct * circumference;
  const [from, to] = TONE_GRAD[tone] ?? TONE_GRAD.signal;
  return (
    <div
      className={cn("relative inline-flex items-center justify-center", className)}
      style={{ width: size, height: size }}
    >
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        className="-rotate-90"
        aria-hidden
      >
        <defs>
          <linearGradient id={`sw-gauge-${id}`} x1="0" x2="1" y1="0" y2="1">
            <stop offset="0%" stopColor={from} />
            <stop offset="100%" stopColor={to} />
          </linearGradient>
        </defs>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--surface-soft-strong)"
          strokeWidth={thickness}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={`url(#sw-gauge-${id})`}
          strokeWidth={thickness}
          strokeDasharray={`${dash} ${circumference}`}
          strokeLinecap="round"
          style={{ transition: "stroke-dasharray 600ms var(--ease-out)" }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-[22px] font-bold tabular leading-none text-[var(--text-primary)]">
          {Math.round(displayValue)}
        </span>
        {label && (
          <span className="text-[11px] font-medium text-[var(--text-secondary)] mt-1">
            {label}
          </span>
        )}
        {sublabel && (
          <span className="text-[10px] text-[var(--text-muted)] mt-0.5">{sublabel}</span>
        )}
      </div>
    </div>
  );
}
