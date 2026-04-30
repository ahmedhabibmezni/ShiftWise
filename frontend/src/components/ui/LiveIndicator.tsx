import { cn } from "@/lib/cn";

export function LiveIndicator({
  label = "live",
  className,
}: {
  label?: string | null;
  className?: string;
}) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <span
        aria-hidden
        className="block h-3 w-3 bg-signal"
        style={{ animation: "shiftwise-pulse 1.6s ease-in-out infinite" }}
      />
      {label && (
        <span className="font-mono text-[12px] uppercase tracking-[0.04em] text-ink-muted">
          {label}
        </span>
      )}
    </span>
  );
}
