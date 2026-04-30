import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

type Variant = "primary" | "secondary" | "danger";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  loading?: boolean;
};

const base =
  "inline-flex h-8 items-center justify-center gap-2 px-3 border rounded-sm " +
  "font-mono text-[11px] uppercase tracking-[0.05em] " +
  "transition-[background-color,border-color,color,opacity] " +
  "disabled:opacity-50 disabled:cursor-not-allowed " +
  "focus:outline-none focus-visible:outline focus-visible:outline-1 " +
  "focus-visible:outline-signal focus-visible:outline-offset-1";

const variants: Record<Variant, string> = {
  primary:
    "bg-signal text-white border-signal hover:bg-[color-mix(in_srgb,var(--signal)_88%,black)] " +
    "hover:border-[color-mix(in_srgb,var(--signal)_88%,black)] active:opacity-90",
  secondary:
    "bg-transparent text-ink border-line hover:bg-bg-elev active:bg-bg-elev",
  danger:
    "bg-err text-white border-err hover:bg-[color-mix(in_srgb,var(--err)_88%,black)] " +
    "hover:border-[color-mix(in_srgb,var(--err)_88%,black)]",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = "secondary", loading, className, disabled, children, ...rest }, ref) => {
    return (
      <button
        ref={ref}
        className={cn(base, variants[variant], className)}
        disabled={disabled || loading}
        data-loading={loading || undefined}
        {...rest}
      >
        {loading ? <span className="opacity-60">…</span> : children}
      </button>
    );
  },
);
Button.displayName = "Button";
