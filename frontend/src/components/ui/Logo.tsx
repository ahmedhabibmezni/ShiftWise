import type { CSSProperties } from "react";
import { useTheme } from "@/hooks/useTheme";
import { cn } from "@/lib/cn";

const ALT = "ShiftWise — VM Migration Console";

type LogoProps = { className?: string; style?: CSSProperties };

/**
 * Full horizontal wordmark (icon + "ShiftWise" + tagline).
 *
 * Swaps between the two delivered brand assets so the wordmark text stays
 * legible on whatever surface it sits on:
 *   - dark theme  → `Horizontal_Dark_Mode.png`  (light text)
 *   - light theme → `Horizontal_Light_Mode.png` (dark text)
 *
 * Height is caller-controlled via `className` (e.g. `h-10`); width is `auto`
 * so the source aspect ratio is preserved.
 */
export function BrandLogo({ className, style }: LogoProps) {
  const { theme } = useTheme();
  const src =
    theme === "dark" ? "/Horizontal_Dark_Mode.png" : "/Horizontal_Light_Mode.png";

  return (
    <img
      src={src}
      alt={ALT}
      className={cn("w-auto object-contain select-none", className)}
      style={style}
      draggable={false}
    />
  );
}

/**
 * Standalone square icon mark (the layered-stack glyph, no wordmark).
 * Theme-independent — used where space is tight or the text would not fit.
 */
export function BrandMark({ className, style }: LogoProps) {
  return (
    <img
      src="/Logo.png"
      alt={ALT}
      className={cn("object-contain select-none", className)}
      style={style}
      draggable={false}
    />
  );
}
