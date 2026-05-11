import { cn } from "@/lib/cn";

export function Gauge({
  value,
  max = 100,
  size = 96,
  thickness = 8,
  label,
  tone = "signal",
  className,
}: {
  value: number;
  max?: number;
  size?: number;
  thickness?: number;
  label?: string;
  tone?: "ok" | "warn" | "err" | "signal" | "info";
  className?: string;
}) {
  const pct = Math.max(0, Math.min(1, value / max));
  const radius = (size - thickness) / 2;
  const circumference = 2 * Math.PI * radius;
  const dash = pct * circumference;
  const color = `var(--${tone === "signal" ? "signal" : tone})`;

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
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--line)"
          strokeWidth={thickness}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={thickness}
          strokeDasharray={`${dash} ${circumference}`}
          strokeLinecap="butt"
          style={{ transition: "stroke-dasharray 500ms var(--ease-out)" }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="font-mono font-semibold text-[22px] tabular leading-none" style={{ color }}>
          {Math.round(value)}
        </span>
        {label && (
          <span className="kicker mt-1">{label}</span>
        )}
      </div>
    </div>
  );
}
