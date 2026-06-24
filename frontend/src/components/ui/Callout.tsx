import type { ReactNode } from "react";
import { AlertCircle, AlertTriangle, CheckCircle2, Info, Zap } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Icon } from "./Icon";
import { cn } from "@/lib/cn";

type Tone = "err" | "warn" | "info" | "signal" | "ok";

const TONE_BG: Record<Tone, string> = {
  err:    "rgba(224, 61, 61, 0.08)",
  warn:   "rgba(232, 146, 42, 0.08)",
  info:   "rgba(62, 111, 212, 0.08)",
  signal: "rgba(230, 38, 0, 0.08)",
  ok:     "rgba(1, 181, 116, 0.08)",
};

const TONE_BORDER: Record<Tone, string> = {
  err:    "rgba(224, 61, 61, 0.3)",
  warn:   "rgba(232, 146, 42, 0.3)",
  info:   "rgba(62, 111, 212, 0.3)",
  signal: "rgba(230, 38, 0, 0.3)",
  ok:     "rgba(1, 181, 116, 0.3)",
};

const TONE_FG: Record<Tone, string> = {
  err:    "var(--alert-critical)",
  warn:   "var(--alert-high)",
  info:   "var(--blue-mid)",
  signal: "var(--accent-light)",
  ok:     "var(--alert-success-light)",
};

const TONE_ICON: Record<Tone, LucideIcon> = {
  err: AlertCircle,
  warn: AlertTriangle,
  info: Info,
  signal: Zap,
  ok: CheckCircle2,
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
        "flex items-start gap-3 rounded-xl px-4 py-3 border",
        className,
      )}
      style={{
        background: TONE_BG[tone],
        borderColor: TONE_BORDER[tone],
      }}
    >
      {IconCmp && (
        <span className="shrink-0 mt-[1px]" style={{ color: TONE_FG[tone] }}>
          <Icon icon={IconCmp} size={16} />
        </span>
      )}
      <div className="min-w-0 flex-1 text-[13px] leading-relaxed">
        {hasKicker && (
          <div
            className="font-bold mb-0.5 uppercase tracking-[0.04em] text-[10px]"
            style={{ color: TONE_FG[tone] }}
          >
            {kicker}
          </div>
        )}
        <div className="text-[var(--text-primary)]">{children}</div>
      </div>
    </div>
  );
}
