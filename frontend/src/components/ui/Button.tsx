import { forwardRef } from "react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/cn";

type Variant = "primary" | "secondary" | "danger" | "ghost";
type Size = "sm" | "md";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  leadingIcon?: ReactNode;
  trailingIcon?: ReactNode;
};

const VARIANTS: Record<Variant, string> = {
  primary:
    "text-white border-transparent shadow-[var(--shadow-accent)] hover:brightness-110 active:brightness-95",
  secondary:
    "glass-card text-[var(--text-primary)] hover:bg-[var(--surface-soft-strong)]",
  danger:
    "bg-[var(--alert-critical)] text-white border-transparent hover:brightness-110 active:brightness-95",
  ghost:
    "bg-transparent text-[var(--text-secondary)] border-transparent hover:text-[var(--text-primary)] hover:bg-[var(--surface-soft-strong)]",
};

const SIZES: Record<Size, string> = {
  sm: "h-8 px-3 text-[12px] rounded-[10px]",
  md: "h-10 px-4 text-[13px] rounded-[12px]",
};

export const Button = forwardRef<HTMLButtonElement, Props>(function Button(
  {
    variant = "secondary",
    size = "md",
    loading,
    leadingIcon,
    trailingIcon,
    className,
    children,
    disabled,
    style,
    // HTML defaults a <button> inside a <form> to type="submit". An
    // unannotated action button (Cancel, Edit, Test Connection, …) placed
    // in a form would therefore submit it. Default to "button"; callers
    // that genuinely submit pass type="submit" explicitly.
    type = "button",
    ...rest
  },
  ref,
) {
  // Primary is the brand gradient — applied inline so the gradient survives
  // any utility-class overrides callers might pass.
  const primaryStyle: React.CSSProperties | undefined =
    variant === "primary"
      ? {
          background:
            "linear-gradient(135deg, var(--accent-primary) 0%, var(--accent-light) 100%)",
        }
      : undefined;

  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      style={{ ...primaryStyle, ...style }}
      className={cn(
        "sw-press inline-flex items-center justify-center gap-2 font-semibold",
        "transition-all duration-200",
        "disabled:opacity-50 disabled:cursor-not-allowed",
        "border",
        SIZES[size],
        VARIANTS[variant],
        className,
      )}
      {...rest}
    >
      {loading ? (
        <Loader2
          className="sw-spin"
          size={size === "sm" ? 14 : 16}
          strokeWidth={2.25}
          aria-label="Loading"
        />
      ) : (
        leadingIcon
      )}
      {children && <span className="leading-none">{children}</span>}
      {!loading && trailingIcon}
    </button>
  );
});
