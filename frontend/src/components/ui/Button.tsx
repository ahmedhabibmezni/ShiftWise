import { forwardRef } from "react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/cn";

type Variant = "primary" | "secondary" | "danger" | "ghost";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  loading?: boolean;
  uppercase?: boolean;
  leadingIcon?: ReactNode;
  trailingIcon?: ReactNode;
};

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-signal text-signal-ink border-transparent hover:brightness-95 active:brightness-90",
  secondary:
    "bg-transparent text-ink border-line-strong hover:bg-bg-elev active:bg-bg-elev-2",
  danger:
    "bg-err text-white border-transparent hover:brightness-95 active:brightness-90",
  ghost:
    "bg-transparent text-ink-muted border-transparent hover:bg-bg-elev hover:text-ink",
};

export const Button = forwardRef<HTMLButtonElement, Props>(function Button(
  {
    variant = "secondary",
    loading,
    uppercase,
    leadingIcon,
    trailingIcon,
    className,
    children,
    disabled,
    ...rest
  },
  ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={cn(
        "sw-press inline-flex h-10 items-center justify-center gap-2 px-4 rounded-sm border",
        "font-sans text-[13px] font-semibold",
        "transition-[background-color,color,border-color,opacity,transform] duration-150",
        "disabled:opacity-50 disabled:cursor-not-allowed",
        "focus-visible:outline-1 focus-visible:outline-signal focus-visible:outline-offset-1",
        uppercase && "uppercase tracking-[0.06em]",
        VARIANTS[variant],
        className,
      )}
      {...rest}
    >
      {loading ? (
        <span className="font-mono tabular text-[12px]">…</span>
      ) : (
        leadingIcon
      )}
      {children}
      {!loading && trailingIcon}
    </button>
  );
});
