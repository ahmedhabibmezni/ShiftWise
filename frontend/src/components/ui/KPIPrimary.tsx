import type { ReactNode } from "react";
import { ArrowUpRight } from "lucide-react";
import { cn } from "@/lib/cn";
import { Icon } from "./Icon";

type Tone = "signal" | "info";

const TONES: Record<Tone, { bg: string; ink: string; rule: string }> = {
  signal: { bg: "var(--signal)", ink: "var(--signal-ink)", rule: "rgba(255,255,255,0.25)" },
  info: { bg: "var(--info)", ink: "var(--info-ink)", rule: "rgba(255,255,255,0.18)" },
};

export function KPIPrimary({
  label,
  value,
  tone = "signal",
  headline,
  children,
  cta,
  onCta,
  className,
}: {
  label: string;
  value?: string;
  tone?: Tone;
  headline?: string;
  children?: ReactNode;
  cta?: string;
  onCta?: () => void;
  className?: string;
}) {
  const t = TONES[tone];
  return (
    <section
      className={cn("flex flex-col", className)}
      style={{ backgroundColor: t.bg, color: t.ink }}
    >
      <div className="p-8 flex-1">
        <div className="text-h3 lowercase opacity-95">{label}</div>
        {value && (
          <div
            className="text-display mt-6 tabular"
            style={{ fontFeatureSettings: '"tnum"' }}
          >
            {value}
          </div>
        )}
        {headline && <div className="text-h2 lowercase mt-4 max-w-xl">{headline}</div>}
        {children && (
          <div className="mt-6">
            {value && (
              <div className="h-px mb-4" style={{ backgroundColor: t.rule }} />
            )}
            {children}
          </div>
        )}
      </div>
      {cta && (
        <button
          type="button"
          onClick={onCta}
          className="h-12 px-6 flex items-center justify-between text-left text-[14px] font-semibold border-t transition-colors duration-150 hover:brightness-95"
          style={{ borderColor: t.rule, color: t.ink }}
        >
          <span className="lowercase">{cta}</span>
          <Icon icon={ArrowUpRight} size={20} />
        </button>
      )}
    </section>
  );
}
