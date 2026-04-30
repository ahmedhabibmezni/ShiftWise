import { forwardRef, type InputHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, "type">;

export const Checkbox = forwardRef<HTMLInputElement, Props>(
  ({ className, ...rest }, ref) => (
    <input
      ref={ref}
      type="checkbox"
      className={cn(
        "h-4 w-4 appearance-none border border-line bg-bg rounded-none align-middle",
        "checked:bg-signal checked:border-signal",
        "checked:bg-[url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%2210%22 height=%228%22 viewBox=%220 0 10 8%22><path fill=%22none%22 stroke=%22white%22 stroke-width=%221.5%22 d=%22M1 4l3 3 5-6%22/></svg>')] checked:bg-[length:10px_8px] checked:bg-center checked:bg-no-repeat",
        "transition-[background-color,border-color]",
        "focus:outline-none focus-visible:outline focus-visible:outline-1 focus-visible:outline-signal focus-visible:outline-offset-1",
        className,
      )}
      {...rest}
    />
  ),
);
Checkbox.displayName = "Checkbox";
