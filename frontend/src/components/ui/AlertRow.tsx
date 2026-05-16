import { ChevronRight } from "lucide-react";
import { StatusDot } from "./StatusDot";
import { Badge } from "./Badge";
import { Icon } from "./Icon";
import type { BadgeVariant } from "./Badge";

type Severity = "critical" | "high" | "medium" | "low";

export function AlertRow({
  time,
  message,
  severity,
  onClick,
}: {
  time: string;
  message: string;
  severity: Severity;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full h-14 px-3 -mx-3 flex items-center gap-4 rounded-xl border-b border-[var(--hairline-faint)] last:border-b-0 transition-colors duration-200 hover:bg-[var(--surface-soft)] text-left"
    >
      <StatusDot variant={severity} />
      <span className="text-[12px] tabular text-[var(--text-muted)] w-12 shrink-0">
        {time}
      </span>
      <span className="text-[14px] flex-1 truncate text-[var(--text-primary)]">
        {message}
      </span>
      <Badge variant={severity as BadgeVariant} dot={false}>
        {severity}
      </Badge>
      <Icon icon={ChevronRight} size={14} className="text-[var(--text-muted)]" />
    </button>
  );
}
