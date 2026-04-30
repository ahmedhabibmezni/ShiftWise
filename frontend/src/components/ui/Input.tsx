import { forwardRef, type InputHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

type InputProps = InputHTMLAttributes<HTMLInputElement> & {
  invalid?: boolean;
};

const base =
  "h-8 w-full px-2 bg-bg text-ink border rounded-none text-[13px] " +
  "placeholder:text-ink-muted " +
  "transition-[border-color,background-color] " +
  "disabled:opacity-50 disabled:cursor-not-allowed " +
  "focus:outline-none focus-visible:outline focus-visible:outline-1 " +
  "focus-visible:outline-signal focus-visible:outline-offset-1";

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ invalid, className, ...rest }, ref) => {
    return (
      <input
        ref={ref}
        aria-invalid={invalid || undefined}
        className={cn(base, invalid ? "border-err" : "border-line", className)}
        {...rest}
      />
    );
  },
);
Input.displayName = "Input";
