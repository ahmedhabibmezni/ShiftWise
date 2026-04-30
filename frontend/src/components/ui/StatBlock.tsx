import type { LucideIcon } from "lucide-react";
import { ArrowDown, ArrowUp } from "lucide-react";
import { Icon } from "./Icon";
import { cn } from "@/lib/cn";

export function StatBlock({
  icon,
  label,
  value,
  delta,
  deltaUnit = "vs 24h",
  inkColor,
  className,
}: {
  icon: LucideIcon;
  label: string;
  value: string;
  delta?: { dir: "up" | "down"; value: string; tone: "ok" | "err" };
  deltaUnit?: string;
  inkColor?: string;
  className?: string;
}) {
  const c = inkColor ?? "currentColor";
  const deltaColor =
    delta?.tone === "ok" ? "var(--ok)" : delta?.tone === "err" ? "var(--err)" : "currentColor";

  return (
    <div className={cn("flex flex-col gap-2", className)} style={{ color: c }}>
      <div className="flex items-center gap-2">
        <Icon icon={icon} size={20} />
        <span className="text-h3 lowercase">{label}</span>
      </div>
      <div className="text-major tabular leading-none">{value}</div>
      {delta && (
        <div className="flex items-center gap-1.5 mt-1 opacity-90">
          <Icon icon={delta.dir === "up" ? ArrowUp : ArrowDown} size={16} />
          <span
            className="font-mono text-[12px] tabular"
            style={{ color: deltaColor }}
          >
            {delta.value}
          </span>
          <span className="text-meta opacity-90">{deltaUnit}</span>
        </div>
      )}
    </div>
  );
}
