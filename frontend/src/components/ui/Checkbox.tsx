import { forwardRef } from "react";
import type { InputHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

export const Checkbox = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Checkbox({ className, ...rest }, ref) {
    return (
      <input
        ref={ref}
        type="checkbox"
        className={cn(
          "shiftwise-checkbox",
          "appearance-none h-4 w-4 rounded-sm border border-line-strong bg-bg-elev",
          "checked:bg-signal checked:border-signal",
          "transition-[background-color,border-color] duration-150",
          "focus-visible:outline-1 focus-visible:outline-signal focus-visible:outline-offset-1",
          "disabled:opacity-50 disabled:cursor-not-allowed",
          className,
        )}
        {...rest}
      />
    );
  },
);
