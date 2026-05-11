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
        "flex flex-col items-center justify-center text-center py-12 px-6 gap-3",
        className,
      )}
    >
      {icon && (
        <div className="relative">
          <span
            aria-hidden
            className="absolute inset-0 rounded-sm bg-bg-elev-2"
            style={{ transform: "translate(4px, 4px)" }}
          />
          <span className="relative inline-flex h-12 w-12 items-center justify-center rounded-sm border border-line-strong bg-bg-elev text-ink-muted">
            <Icon icon={icon} size={20} />
          </span>
        </div>
      )}
      <div className="text-h3 lowercase text-ink mt-2">{title}</div>
      {hint && (
        <p className="font-mono text-[11px] text-ink-muted max-w-[44ch] lowercase">
          {hint}
        </p>
      )}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
