import { ArrowRight } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { OrbitalIllustration } from "./OrbitalIllustration";

/**
 * Dashboard hero — the welcome panel.
 *
 *   ┌────────────────────────────────────────────────────────────┐
 *   │  Welcome back,                          ┌─────────────┐    │
 *   │  Mark Johnson                           │             │    │
 *   │                                         │   ORBITAL   │    │
 *   │  Glad to see you again. 3 campaigns…    │     SVG     │    │
 *   │                                         │             │    │
 *   │  Tap to record →                        └─────────────┘    │
 *   └────────────────────────────────────────────────────────────┘
 *
 * The orbital SVG is positioned bottom-right, bleeding off-panel.
 * A diagonal navy → orange gradient overlay sits between the body orbs and
 * the panel content.
 */
export function HeroWelcome({
  kicker = "Welcome back,",
  name,
  description,
  cta,
  ctaTo = "/migrations",
}: {
  kicker?: string;
  name: ReactNode;
  description?: ReactNode;
  cta?: string;
  ctaTo?: string;
}) {
  return (
    <section className="glass-card relative overflow-hidden flex flex-col justify-between min-h-[340px]">
      {/* Hero overlay gradient */}
      <span
        aria-hidden
        className="absolute inset-0 z-[1] pointer-events-none"
        style={{ background: "var(--hero-gradient)" }}
      />

      {/* Bleed-off orbital SVG, bottom-right */}
      <span
        aria-hidden
        className="absolute pointer-events-none z-[1]"
        style={{
          right: 0,
          bottom: 0,
          width: "60%",
          height: "70%",
        }}
      >
        <OrbitalIllustration className="absolute inset-0 w-full h-full" />
      </span>

      <div className="relative z-[2] p-7">
        <div className="text-[12px] font-medium text-[var(--text-secondary)]">
          {kicker}
        </div>
        <h2 className="mt-2 text-[28px] font-bold tracking-[-0.02em] leading-[1.1] text-[var(--text-primary)]">
          {name}
        </h2>
        {description && (
          <p className="mt-3.5 max-w-[42ch] text-[13px] leading-relaxed text-[var(--text-secondary)]">
            {description}
          </p>
        )}
        {cta && (
          <Link
            to={ctaTo}
            className="group mt-7 inline-flex items-center gap-1.5 hover:gap-2.5 text-[12px] font-bold text-[var(--text-primary)] hover:text-[var(--accent-light)] transition-all duration-200"
          >
            {cta}
            <ArrowRight size={12} strokeWidth={2.25} />
          </Link>
        )}
      </div>
    </section>
  );
}
