import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/cn";

type IconProps = {
  icon: LucideIcon;
  size?: 16 | 20;
  className?: string;
  "aria-label"?: string;
};

export function Icon({ icon: LucideComp, size = 16, className, ...rest }: IconProps) {
  return (
    <LucideComp
      size={size}
      strokeWidth={1.5}
      className={cn("inline-block shrink-0", className)}
      aria-hidden={rest["aria-label"] ? undefined : true}
      {...rest}
    />
  );
}
