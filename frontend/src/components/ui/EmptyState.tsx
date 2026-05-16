import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Icon } from "./Icon";
import { cn } from "@/lib/cn";

export function EmptyState({
  icon,
  title,
  hint,
  action,
  className,
}: {
  icon?: LucideIcon;
  title: string;
  hint?: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center text-center py-12 px-6 gap-4",
        className,
      )}
    >
      {icon && (
        <span
          aria-hidden
          className="icon-container icon-container--muted h-16 w-16 rounded-2xl"
        >
          <Icon icon={icon} size={28} strokeWidth={1.5} />
        </span>
      )}
      <div className="text-[18px] font-bold tracking-[-0.01em] text-[var(--text-primary)] mt-1">
        {title}
      </div>
      {hint && (
        <p className="text-[13px] text-[var(--text-secondary)] max-w-[44ch] leading-relaxed">
          {hint}
        </p>
      )}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
