import { forwardRef } from "react";
import type { InputHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

type Props = InputHTMLAttributes<HTMLInputElement> & { invalid?: boolean };

export const Input = forwardRef<HTMLInputElement, Props>(function Input(
  { className, invalid, ...rest },
  ref,
) {
  return (
    <input
      ref={ref}
      aria-invalid={invalid || undefined}
      className={cn(
        "w-full h-10 px-3.5 rounded-xl border bg-[var(--surface-soft)]",
        "text-[var(--text-primary)] text-[14px] font-medium",
        "placeholder:text-[var(--text-muted)] placeholder:font-normal",
        "transition-all duration-200",
        invalid
          ? "border-[var(--alert-critical)]/60"
          : "border-[var(--hairline)] hover:border-[var(--accent-light)]/50 focus:border-[var(--accent-primary)]/60",
        "focus:outline-none focus:bg-[var(--surface-soft-strong)]",
        "disabled:opacity-50 disabled:cursor-not-allowed",
        className,
      )}
      style={{
        backdropFilter: "blur(20px)",
        WebkitBackdropFilter: "blur(20px)",
      }}
      {...rest}
    />
  );
});
