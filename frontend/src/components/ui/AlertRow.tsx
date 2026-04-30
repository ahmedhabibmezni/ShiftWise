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
      className="w-full h-14 px-4 flex items-center gap-4 border-b border-line last:border-b-0 transition-colors duration-150 hover:bg-bg-elev-2 text-left"
    >
      <StatusDot variant={severity} />
      <span className="font-mono text-[12px] tabular text-ink-muted w-12 shrink-0">
        {time}
      </span>
      <span className="text-[14px] flex-1 truncate">{message}</span>
      <Badge variant={severity as BadgeVariant} dot={false}>
        {severity}
      </Badge>
      <Icon icon={ChevronRight} size={16} className="text-ink-muted" />
    </button>
  );
}
