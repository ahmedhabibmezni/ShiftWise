import type { LucideIcon } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";
import { cn } from "@/lib/cn";

type Density = "comfortable" | "compact";
type IconTone = "accent" | "blue" | "success" | "warn" | "muted";

const ICON_CLASS_BY_TONE: Record<IconTone, string> = {
  accent: "icon-container icon-container--accent",
  blue: "icon-container icon-container--blue",
  success: "icon-container icon-container--success",
  warn: "icon-container icon-container--warn",
  muted: "icon-container icon-container--muted",
};

// Map legacy iconTone names to the new icon-container variants so callers
// that still pass `iconTone="signal"` keep working.
const LEGACY_ICON_TONE_MAP: Record<string, IconTone> = {
  ok: "success",
  warn: "warn",
  err: "accent",
  signal: "accent",
  info: "blue",
};

/**
 * Panel — the foundational glass card primitive.
 *
 * Recipe (per DESIGN.md):
 *   background:        var(--card-gradient)
 *   backdrop-filter:   blur(120px)
 *   border-radius:     20px
 *   box-shadow:        var(--card-shadow)
 *   + ::before 1px gradient border via mask-composite
 *
 * The body radial orbs (declared on body::before in base.css) bleed through
 * the 120px blur. DO NOT apply opacity/transform/filter/will-change/mask
 * to any ANCESTOR of this element — it creates a backdrop-root and silently
 * breaks the blur. The .sw-mount wrapper does transform but is intentionally
 * a sibling-level animation wrapper, not an ancestor of further glass cards.
 *
 * Every Panel is a glass card. There is no solid-fill variant: surfaces that
 * need a coloured fill (the hero) layer a gradient overlay over the glass.
 */
export function Panel({
  icon: PanelIcon,
  iconTone,
  kicker,
  title,
  hint,
  action,
  footer,
  density = "comfortable",
  className,
  bodyClassName,
  children,
  interactive,
  onClick,
  asSection = true,
  variant = "default",
  style,
}: {
  icon?: LucideIcon;
  iconTone?: IconTone | "ok" | "warn" | "err" | "signal" | "info";
  kicker?: string;
  title?: ReactNode;
  hint?: ReactNode;
  action?: ReactNode;
  footer?: ReactNode;
  density?: Density;
  className?: string;
  bodyClassName?: string;
  children?: ReactNode;
  interactive?: boolean;
  onClick?: () => void;
  asSection?: boolean;
  /** "lite" reduces blur to 60px for pages with many cards. */
  variant?: "default" | "lite" | "nested";
  style?: CSSProperties;
}) {
  const Tag = asSection ? "section" : "div";
  const hasHeader = !!(kicker || title || action || PanelIcon);

  const normalisedIconTone = iconTone
    ? (LEGACY_ICON_TONE_MAP[iconTone] ?? (iconTone as IconTone))
    : "accent";
  const iconClass = ICON_CLASS_BY_TONE[normalisedIconTone];

  const variantClass =
    variant === "lite"
      ? "glass-card glass-card--lite"
      : variant === "nested"
        ? "glass-card--nested"
        : "glass-card";

  return (
    <Tag
      onClick={onClick}
      style={style}
      className={cn(
        "relative flex flex-col overflow-hidden",
        variantClass,
        interactive &&
          "cursor-pointer transition-shadow duration-200 hover:shadow-[var(--shadow-hover)]",
        className,
      )}
    >
      {hasHeader && (
        <header
          className={cn(
            "relative flex items-start justify-between gap-3 z-[1]",
            density === "compact" ? "px-5 pt-4 pb-2" : "px-6 pt-5 pb-3",
          )}
        >
          <div className="min-w-0 flex-1 flex items-start gap-3">
            {PanelIcon && (
              <span
                aria-hidden
                className={cn(iconClass, "shrink-0 mt-0.5 w-9 h-9 rounded-xl")}
              >
                <PanelIcon size={16} strokeWidth={1.75} />
              </span>
            )}
            <div className="min-w-0 flex-1">
              {kicker && <div className="kicker mb-1.5">{kicker}</div>}
              {title && (
                <h3
                  className={cn(
                    "leading-tight truncate font-bold text-[var(--text-primary)]",
                    density === "compact"
                      ? "text-[14px]"
                      : "text-[18px] tracking-[-0.01em]",
                  )}
                >
                  {title}
                </h3>
              )}
              {hint && (
                <div className="mt-1 text-[12px] text-[var(--text-secondary)]">
                  {hint}
                </div>
              )}
            </div>
          </div>
          {action && <div className="shrink-0 flex items-center gap-2">{action}</div>}
        </header>
      )}

      <div
        className={cn(
          "relative z-[1]",
          density === "compact" ? "px-5 pb-4" : "px-6 pb-5",
          !hasHeader && (density === "compact" ? "pt-4" : "pt-5"),
          "flex-1",
          bodyClassName,
        )}
      >
        {children}
      </div>

      {footer && (
        <footer
          className={cn(
            "relative z-[1] border-t border-[var(--hairline)]",
            density === "compact" ? "px-5 py-2" : "px-6 py-3",
          )}
        >
          {footer}
        </footer>
      )}
    </Tag>
  );
}
