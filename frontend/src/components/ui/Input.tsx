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
        "w-full h-10 px-3 rounded-sm border bg-bg-elev text-ink",
        "font-sans text-[14px] placeholder:text-ink-muted",
        "transition-[border-color,outline-color] duration-150",
        invalid ? "border-err" : "border-line hover:border-line-strong",
        "focus:outline-none focus-visible:outline-1 focus-visible:outline-signal focus-visible:outline-offset-0",
        "disabled:opacity-50 disabled:cursor-not-allowed",
        className,
      )}
      {...rest}
    />
  );
});
