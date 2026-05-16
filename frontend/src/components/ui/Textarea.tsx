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
      style={{
        backdropFilter: "blur(20px)",
        WebkitBackdropFilter: "blur(20px)",
      }}
      className={cn(
        "w-full min-h-[88px] px-3.5 py-2.5 rounded-xl border bg-[var(--surface-soft)]",
        "text-[var(--text-primary)] text-[14px] font-medium",
        "placeholder:text-[var(--text-muted)] placeholder:font-normal",
        "transition-all duration-200 resize-y",
        invalid
          ? "border-[var(--alert-critical)]/60"
          : "border-[var(--hairline)] hover:border-[var(--accent-light)]/50 focus:border-[var(--accent-primary)]/60",
        "focus:outline-none focus:bg-[var(--surface-soft-strong)]",
        "disabled:opacity-50 disabled:cursor-not-allowed",
        className,
      )}
      {...rest}
    />
  );
});
