import { ArrowUp } from "lucide-react";
import { cn } from "@/lib/cn";

/**
 * Larger metric tile — display-scale value with optional delta line.
 * Used on pages where the metric needs more visual weight than KPIPrimary.
 */
export function KPISecondary({
  label,
  value,
  suffix,
  delta,
  deltaUnit = "vs 24h",
  className,
}: {
  label: string;
  value: string;
  suffix?: string;
  delta?: { dir: "up" | "down" | "flat"; value: string; tone?: "ok" | "err" | "muted" };
  deltaUnit?: string;
  className?: string;
}) {
  const tone =
    delta?.tone ?? (delta?.dir === "up" ? "ok" : delta?.dir === "down" ? "err" : "muted");
  const deltaColor =
    tone === "ok"
      ? "var(--alert-success-light)"
      : tone === "err"
        ? "var(--alert-critical)"
        : "var(--text-muted)";

  return (
    <section className={cn("glass-card p-6 flex flex-col", className)}>
      <div className="text-[13px] font-bold text-[var(--text-primary)]">{label}</div>
      <div className="mt-4 flex items-baseline gap-2">
        <div className="text-[40px] font-bold tracking-[-0.025em] tabular text-[var(--text-primary)] leading-none">
          {value}
        </div>
        {suffix && (
          <div className="text-[13px] font-bold text-[var(--text-secondary)]">
            {suffix}
          </div>
        )}
      </div>
      {delta && (
        <div className="mt-auto pt-6 flex items-center gap-2">
          {delta.dir !== "flat" && (
            <ArrowUp
              size={14}
              strokeWidth={2}
              className={cn(delta.dir === "down" && "rotate-180")}
              style={{ color: deltaColor }}
            />
          )}
          <span className="text-[12px] font-bold tabular" style={{ color: deltaColor }}>
            {delta.value}
          </span>
          <span className="text-[12px] text-[var(--text-secondary)]">{deltaUnit}</span>
        </div>
      )}
    </section>
  );
}
