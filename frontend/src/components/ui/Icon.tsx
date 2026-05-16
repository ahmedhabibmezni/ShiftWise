import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/cn";

type Size = 10 | 11 | 12 | 13 | 14 | 16 | 18 | 20 | 22 | 24 | 28 | 32 | 40;

/**
 * Icon — wraps any lucide-react icon with the ShiftWise default stroke width.
 * Per DESIGN.md, strokeWidth is 1.75 across the system.
 */
export function Icon({
  icon: I,
  size = 16,
  strokeWidth = 1.75,
  className,
  style,
}: {
  icon: LucideIcon;
  size?: Size;
  strokeWidth?: number;
  className?: string;
  style?: React.CSSProperties;
}) {
  return (
    <I
      size={size}
      strokeWidth={strokeWidth}
      className={cn("shrink-0", className)}
      style={style}
      aria-hidden
    />
  );
}
