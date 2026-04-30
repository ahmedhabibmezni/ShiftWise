import { cn } from "@/lib/cn";

export function LiveIndicator({ className }: { className?: string }) {
  return (
    <span
      aria-label="En cours"
      className={cn(
        "inline-block h-2 w-2 bg-signal align-middle",
        "[animation:shiftwise-pulse_1.6s_ease-in-out_infinite]",
        className,
      )}
    />
  );
}
