import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { usePrefersReducedMotion } from "@/hooks/usePrefersReducedMotion";

export function Ticker({
  items,
  speed = 40,
  className,
}: {
  items: ReactNode[];
  speed?: number;
  className?: string;
}) {
  const reducedMotion = usePrefersReducedMotion();
  if (items.length === 0) return null;

  if (reducedMotion) {
    return (
      <div
        className={cn(
          "relative overflow-x-auto",
          "[mask-image:linear-gradient(to_right,transparent_0,black_8%,black_92%,transparent_100%)]",
          className,
        )}
      >
        <div className="flex items-center gap-8 whitespace-nowrap">
          {items.map((it, i) => (
            <span key={i} className="flex items-center gap-2 shrink-0">
              {it}
            </span>
          ))}
        </div>
      </div>
    );
  }

  const doubled = [...items, ...items];
  const duration = `${(items.length * speed).toFixed(0)}s`;
  return (
    <div
      className={cn(
        "relative overflow-hidden",
        "[mask-image:linear-gradient(to_right,transparent_0,black_8%,black_92%,transparent_100%)]",
        className,
      )}
    >
      <div
        className="flex items-center gap-8 whitespace-nowrap will-change-transform"
        style={{ animation: `shiftwise-marquee ${duration} linear infinite` }}
      >
        {doubled.map((it, i) => (
          <span key={i} className="flex items-center gap-2 shrink-0">
            {it}
          </span>
        ))}
      </div>
    </div>
  );
}
