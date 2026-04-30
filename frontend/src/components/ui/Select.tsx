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
        backgroundPosition: "right 12px center",
        backgroundSize: "12px 12px",
      }}
      className={cn(
        "w-full h-10 pl-3 pr-9 rounded-sm border bg-bg-elev text-ink appearance-none",
        "font-sans text-[14px]",
        "transition-[border-color] duration-150",
        invalid ? "border-err" : "border-line hover:border-line-strong",
        "focus:outline-none focus-visible:outline-1 focus-visible:outline-signal",
        "disabled:opacity-50 disabled:cursor-not-allowed",
        className,
      )}
      {...rest}
    >
      {children}
    </select>
  );
});
