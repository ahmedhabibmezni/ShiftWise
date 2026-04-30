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
      className="w-full h-10 px-3 -mx-3 grid items-center gap-4 text-left transition-colors duration-150 hover:bg-black/10"
      style={{
        gridTemplateColumns: "180px 80px 56px 1fr 80px 80px 16px",
      }}
    >
      <span className="font-mono text-[13px] tabular flex items-center gap-2">
        {source}
        <Icon icon={ArrowRight} size={16} />
        {target}
      </span>
      <span className="font-mono text-[13px] tabular opacity-90">{vmId}</span>
      <span className="font-mono text-[13px] tabular text-right">{pct}%</span>
      <ProgressBar value={pct} variant="white" />
      <span className="font-mono text-[13px] tabular text-right opacity-90">{size}</span>
      <span className="font-mono text-[13px] tabular text-right opacity-90">{duration}</span>
      <Icon icon={ChevronRight} size={16} />
    </button>
  );
}
