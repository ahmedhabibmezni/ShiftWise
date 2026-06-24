import { forwardRef } from "react";
import type { InputHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

export const Checkbox = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Checkbox({ className, style, ...rest }, ref) {
    return (
      <input
        ref={ref}
        type="checkbox"
        className={cn(
          "shiftwise-checkbox",
          "appearance-none h-4 w-4 rounded-[6px]",
          "border border-[var(--hairline)] bg-[var(--surface-soft-strong)]",
          "checked:border-transparent",
          "transition-all duration-200 cursor-pointer",
          "disabled:opacity-50 disabled:cursor-not-allowed",
          className,
        )}
        style={style}
        {...rest}
      />
    );
  },
);
