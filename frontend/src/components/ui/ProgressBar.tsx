import { cn } from "@/lib/cn";

type Props = {
  value: number;
  showPct?: boolean;
  className?: string;
};

export function ProgressBar({ value, showPct = false, className }: Props) {
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <div
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        className="h-1 flex-1 bg-bg-elev relative overflow-hidden"
      >
        <div
          className="absolute inset-y-0 left-0 bg-signal transition-[width] duration-[120ms]"
          style={{ width: `${pct}%` }}
        />
      </div>
      {showPct && (
        <span className="font-mono tabular-nums text-[11px] text-ink-muted w-9 text-right">
          {pct.toFixed(0)}%
        </span>
      )}
    </div>
  );
}
