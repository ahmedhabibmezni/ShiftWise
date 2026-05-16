import { forwardRef } from "react";
import type { SelectHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

type Props = SelectHTMLAttributes<HTMLSelectElement> & { invalid?: boolean };

const CHEVRON =
  "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='1.5'><polyline points='6 9 12 15 18 9'/></svg>\")";

export const Select = forwardRef<HTMLSelectElement, Props>(function Select(
  { className, invalid, children, ...rest },
  ref,
) {
  return (
    <select
      ref={ref}
      aria-invalid={invalid || undefined}
      style={{
        backgroundImage: CHEVRON,
        backgroundRepeat: "no-repeat",
        backgroundPosition: "right 14px center",
        backgroundSize: "12px 12px",
        backdropFilter: "blur(20px)",
        WebkitBackdropFilter: "blur(20px)",
      }}
      className={cn(
        "w-full h-10 pl-3.5 pr-10 rounded-xl border bg-[var(--surface-soft)] appearance-none",
        "text-[var(--text-primary)] text-[14px] font-medium",
        "transition-all duration-200",
        invalid
          ? "border-[var(--alert-critical)]/60"
          : "border-[var(--hairline)] hover:border-[var(--accent-light)]/50 focus:border-[var(--accent-primary)]/60",
        "focus:outline-none focus:bg-[var(--surface-soft-strong)]",
        "disabled:opacity-50 disabled:cursor-not-allowed",
        className,
      )}
      {...rest}
    >
      {children}
    </select>
  );
});
