import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/cn";

type Size = 16 | 20;

export function Icon({
  icon: I,
  size = 16,
  className,
}: {
  icon: LucideIcon;
  size?: Size;
  className?: string;
}) {
  return <I size={size} strokeWidth={1.5} className={cn("shrink-0", className)} aria-hidden />;
}
