import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export function SectionHeading({
  kicker,
  title,
  action,
  className,
}: {
  kicker?: string;
  title: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <header className={cn("flex items-end justify-between gap-4 mb-4", className)}>
      <div>
        {kicker && <div className="kicker mb-1">{kicker}</div>}
        <h2 className="text-h2 lowercase">{title}</h2>
      </div>
      {action}
    </header>
  );
}
