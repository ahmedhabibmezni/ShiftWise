import { ArrowRight, ChevronRight } from "lucide-react";
import { Icon } from "./Icon";
import { ProgressBar } from "./ProgressBar";

export function MiniRow({
  source,
  target,
  vmId,
  pct,
  size,
  duration,
  onClick,
}: {
  source: string;
  target: string;
  vmId: string;
  pct: number;
  size: string;
  duration: string;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full h-11 px-3 -mx-3 grid items-center gap-4 text-left rounded-xl transition-colors duration-200 hover:bg-[var(--surface-soft)]"
      style={{
        gridTemplateColumns: "180px 80px 56px 1fr 80px 80px 16px",
      }}
    >
      <span className="text-[13px] tabular font-medium flex items-center gap-2">
        {source}
        <Icon icon={ArrowRight} size={14} />
        {target}
      </span>
      <span className="text-[13px] tabular text-[var(--text-secondary)]">{vmId}</span>
      <span className="text-[13px] tabular font-bold text-right">{pct}%</span>
      <ProgressBar value={pct} variant="signal" />
      <span className="text-[13px] tabular text-right text-[var(--text-secondary)]">
        {size}
      </span>
      <span className="text-[13px] tabular text-right text-[var(--text-secondary)]">
        {duration}
      </span>
      <Icon icon={ChevronRight} size={14} />
    </button>
  );
}
