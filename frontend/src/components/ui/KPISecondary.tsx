import { ArrowDown, ArrowUp } from "lucide-react";
import { cn } from "@/lib/cn";
import { Icon } from "./Icon";

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
  const tone = delta?.tone ?? (delta?.dir === "up" ? "ok" : delta?.dir === "down" ? "err" : "muted");
  const deltaColor =
    tone === "ok" ? "var(--ok)" : tone === "err" ? "var(--err)" : "var(--ink-muted)";

  return (
    <section
      className={cn("border border-line bg-bg-elev p-6 flex flex-col", className)}
    >
      <div className="text-h3 lowercase text-ink">{label}</div>
      <div className="mt-4 flex items-baseline gap-2">
        <div className="text-major text-ink tabular">{value}</div>
        {suffix && (
          <div className="text-h3 text-ink-muted lowercase">{suffix}</div>
        )}
      </div>
      {delta && (
        <div className="mt-auto pt-6 flex items-center gap-2">
          {delta.dir !== "flat" && (
            <Icon
              icon={delta.dir === "up" ? ArrowUp : ArrowDown}
              size={16}
              className="shrink-0"
            />
          )}
          <span
            className="font-mono text-[12px] tabular"
            style={{ color: deltaColor }}
          >
            {delta.value}
          </span>
          <span className="text-meta text-ink-muted">{deltaUnit}</span>
        </div>
      )}
    </section>
  );
}
