import type { ReactNode } from "react";
import { AlertCircle, AlertTriangle, Info, Zap } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Icon } from "./Icon";
import { cn } from "@/lib/cn";

type Tone = "err" | "warn" | "info" | "signal";

const TONE_BG: Record<Tone, string> = {
  err: "border-err/40 bg-err/5",
  warn: "border-warn/40 bg-warn/5",
  info: "border-info/40 bg-info/5",
  signal: "border-signal/40 bg-signal/5",
};

const TONE_TEXT: Record<Tone, string> = {
  err: "text-err",
  warn: "text-warn",
  info: "text-info-soft",
  signal: "text-signal",
};

const TONE_ICON: Record<Tone, LucideIcon> = {
  err: AlertCircle,
  warn: AlertTriangle,
  info: Info,
  signal: Zap,
};

export function Callout({
  tone = "err",
  kicker,
  icon,
  children,
  className,
  role = "status",
}: {
  tone?: Tone;
  kicker?: string;
  icon?: LucideIcon | false;
  children: ReactNode;
  className?: string;
  role?: "alert" | "status";
}) {
  const IconCmp = icon === false ? null : (icon ?? TONE_ICON[tone]);
  const hasKicker = !!kicker;
  return (
    <div
      role={role}
      className={cn(
        "flex items-start gap-2.5 border rounded-sm px-3 py-2",
        TONE_BG[tone],
        className,
      )}
    >
      {IconCmp && (
        <span className={cn("shrink-0 mt-[1px]", TONE_TEXT[tone])}>
          <Icon icon={IconCmp} size={14} />
        </span>
      )}
      <div className="min-w-0 flex-1 font-mono text-[11px] uppercase tracking-[0.04em] leading-relaxed">
        {hasKicker && (
          <div className={cn("font-semibold mb-0.5", TONE_TEXT[tone])}>
            {kicker}
          </div>
        )}
        <div className={hasKicker ? "text-ink normal-case tracking-normal" : TONE_TEXT[tone]}>
          {children}
        </div>
      </div>
    </div>
  );
}
