import { forwardRef } from "react";
import type { TextareaHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

type Props = TextareaHTMLAttributes<HTMLTextAreaElement> & { invalid?: boolean };

export const Textarea = forwardRef<HTMLTextAreaElement, Props>(function Textarea(
  { className, invalid, ...rest },
  ref,
) {
  return (
    <textarea
      ref={ref}
      aria-invalid={invalid || undefined}
      className={cn(
        "w-full min-h-[80px] px-3 py-2 rounded-sm border bg-bg-elev text-ink",
        "font-sans text-[14px] placeholder:text-ink-muted",
        "transition-[border-color] duration-150",
        invalid ? "border-err" : "border-line hover:border-line-strong",
        "focus:outline-none focus-visible:outline-1 focus-visible:outline-signal",
        "disabled:opacity-50 disabled:cursor-not-allowed",
        className,
      )}
      {...rest}
    />
  );
});
