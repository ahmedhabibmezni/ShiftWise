import { forwardRef, type TextareaHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

type Props = TextareaHTMLAttributes<HTMLTextAreaElement> & { invalid?: boolean };

const base =
  "block w-full px-2 py-1 bg-bg text-ink border rounded-none text-[13px] " +
  "placeholder:text-ink-muted " +
  "transition-[border-color] " +
  "disabled:opacity-50 " +
  "focus:outline-none focus-visible:outline focus-visible:outline-1 " +
  "focus-visible:outline-signal focus-visible:outline-offset-1";

export const Textarea = forwardRef<HTMLTextAreaElement, Props>(
  ({ invalid, className, rows = 3, ...rest }, ref) => (
    <textarea
      ref={ref}
      rows={rows}
      aria-invalid={invalid || undefined}
      className={cn(base, invalid ? "border-err" : "border-line", className)}
      {...rest}
    />
  ),
);
Textarea.displayName = "Textarea";
