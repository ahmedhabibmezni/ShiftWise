import { forwardRef } from "react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/cn";

type Variant = "primary" | "secondary" | "ghost";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  "aria-label": string;
  children: ReactNode;
};

const VARIANTS: Record<Variant, string> = {
  primary:
    "text-white shadow-[var(--shadow-accent)] border-transparent hover:brightness-110",
  secondary:
    "glass-card text-[var(--text-primary)] hover:text-[var(--accent-light)]",
  ghost:
    "bg-transparent text-[var(--text-secondary)] border-transparent hover:text-[var(--accent-light)]",
};

export const IconButton = forwardRef<HTMLButtonElement, Props>(function IconButton(
  { variant = "ghost", className, children, style, ...rest },
  ref,
) {
  const primaryStyle =
    variant === "primary"
      ? {
          background:
            "linear-gradient(135deg, var(--accent-primary) 0%, var(--accent-light) 100%)",
        }
      : undefined;
  return (
    <button
      ref={ref}
      style={{ ...primaryStyle, ...style }}
      className={cn(
        "inline-flex h-9 w-9 items-center justify-center rounded-xl border",
        "transition-all duration-200",
        "disabled:opacity-50 disabled:cursor-not-allowed",
        VARIANTS[variant],
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
});
