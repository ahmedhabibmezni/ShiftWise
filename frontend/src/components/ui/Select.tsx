import { forwardRef, type SelectHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

type SelectProps = SelectHTMLAttributes<HTMLSelectElement> & {
  invalid?: boolean;
};

const base =
  "h-8 w-full px-2 pr-7 bg-bg text-ink border rounded-none text-[13px] " +
  "appearance-none " +
  "bg-[url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%2210%22 height=%226%22 viewBox=%220 0 10 6%22><path fill=%22none%22 stroke=%22currentColor%22 stroke-width=%221.5%22 d=%22M1 1l4 4 4-4%22/></svg>')] " +
  "bg-[length:10px_6px] bg-[position:right_8px_center] bg-no-repeat " +
  "transition-[border-color] " +
  "disabled:opacity-50 disabled:cursor-not-allowed " +
  "focus:outline-none focus-visible:outline focus-visible:outline-1 " +
  "focus-visible:outline-signal focus-visible:outline-offset-1";

export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  ({ invalid, className, children, ...rest }, ref) => {
    return (
      <select
        ref={ref}
        aria-invalid={invalid || undefined}
        className={cn(base, invalid ? "border-err" : "border-line", className)}
        {...rest}
      >
        {children}
      </select>
    );
  },
);
Select.displayName = "Select";
