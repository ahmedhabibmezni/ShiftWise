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
  primary: "bg-signal text-signal-ink border-transparent hover:brightness-95",
  secondary:
    "bg-transparent text-ink border-line-strong hover:bg-bg-elev",
  ghost:
    "bg-transparent text-ink-muted border-transparent hover:bg-bg-elev hover:text-ink",
};

export const IconButton = forwardRef<HTMLButtonElement, Props>(function IconButton(
  { variant = "ghost", className, children, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      className={cn(
        "inline-flex h-10 w-10 items-center justify-center rounded-sm border",
        "transition-[background-color,color,border-color] duration-150",
        "disabled:opacity-50 disabled:cursor-not-allowed",
        "focus-visible:outline-1 focus-visible:outline-signal focus-visible:outline-offset-1",
        VARIANTS[variant],
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
});
