import type { ReactNode, ThHTMLAttributes, TdHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

export function Table({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("border border-line overflow-auto", className)}>
      <table className="w-full border-collapse text-[13px]">{children}</table>
    </div>
  );
}

export function THead({ children }: { children: ReactNode }) {
  return (
    <thead className="sticky top-0 bg-bg-elev">
      {children}
    </thead>
  );
}

export function TR({
  children,
  interactive,
  className,
  ...rest
}: {
  children: ReactNode;
  interactive?: boolean;
  className?: string;
  onClick?: () => void;
}) {
  return (
    <tr
      className={cn(
        "border-b border-line-soft last:border-b-0 h-8",
        interactive && "cursor-pointer hover:bg-bg-elev transition-[background-color]",
        className,
      )}
      {...rest}
    >
      {children}
    </tr>
  );
}

type ThProps = ThHTMLAttributes<HTMLTableCellElement> & {
  numeric?: boolean;
};
export function TH({ numeric, className, children, ...rest }: ThProps) {
  return (
    <th
      className={cn(
        "h-8 px-3 font-mono text-[11px] uppercase tracking-[0.05em] text-ink-muted",
        "text-left border-b border-line",
        // double bottom border via pseudo
        "shadow-[inset_0_-1px_0_var(--line-soft)]",
        numeric && "text-right",
        className,
      )}
      {...rest}
    >
      {children}
    </th>
  );
}

type TdProps = TdHTMLAttributes<HTMLTableCellElement> & {
  numeric?: boolean;
  mono?: boolean;
};
export function TD({ numeric, mono, className, children, ...rest }: TdProps) {
  return (
    <td
      className={cn(
        "px-3 align-middle text-ink",
        (numeric || mono) && "font-mono tabular-nums",
        numeric && "text-right",
        className,
      )}
      {...rest}
    >
      {children}
    </td>
  );
}
