import { cn } from "@/lib/cn";

export type StackedSegment = {
  key: string;
  label: string;
  value: number;
  color: string;
};

export function StackedBar({
  segments,
  height = 8,
  showLegend = true,
  className,
}: {
  segments: StackedSegment[];
  height?: number;
  showLegend?: boolean;
  className?: string;
}) {
  const total = segments.reduce((acc, s) => acc + s.value, 0) || 1;
  return (
    <div className={cn("space-y-3", className)}>
      <div
        role="img"
        aria-label="Distribution"
        className="flex w-full overflow-hidden rounded-full"
        style={{ height, backgroundColor: "var(--surface-soft-strong)" }}
      >
        {segments.map((s) => {
          const pct = (s.value / total) * 100;
          if (pct === 0) return null;
          return (
            <span
              key={s.key}
              title={`${s.label}: ${s.value}`}
              style={{ width: `${pct}%`, backgroundColor: s.color }}
              className="h-full transition-[width] duration-[var(--dur-slow)]"
            />
          );
        })}
      </div>
      {showLegend && (
        <ul className="flex flex-wrap gap-x-4 gap-y-1.5">
          {segments.map((s) => {
            const pct = total === 0 ? 0 : (s.value / total) * 100;
            return (
              <li
                key={s.key}
                className="flex items-center gap-2 text-[11px] tabular text-[var(--text-secondary)]"
              >
                <span
                  aria-hidden
                  className="block h-2 w-2 shrink-0 rounded-full"
                  style={{ backgroundColor: s.color }}
                />
                <span className="font-medium">{s.label}</span>
                <span className="text-[var(--text-primary)] font-bold">{s.value}</span>
                <span className="text-[var(--text-muted)]">{pct.toFixed(0)}%</span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
