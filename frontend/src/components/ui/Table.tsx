import type { ReactNode, ThHTMLAttributes, TdHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

export function Table({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("border border-line", className)}>
      <table className="w-full border-collapse">{children}</table>
    </div>
  );
}

export function THead({ children }: { children: ReactNode }) {
  return (
    <thead
      className="bg-bg-elev"
      style={{ boxShadow: "inset 0 -1px 0 var(--line-strong)" }}
    >
      {children}
    </thead>
  );
}

export function TR({
  children,
  interactive,
  className,
}: {
  children: ReactNode;
  interactive?: boolean;
  className?: string;
}) {
  return (
    <tr
      className={cn(
        "border-b border-line last:border-b-0 h-10",
        interactive && "transition-[background-color] duration-150 hover:bg-bg-elev-2 cursor-pointer",
        className,
      )}
    >
      {children}
    </tr>
  );
}

type ThProps = ThHTMLAttributes<HTMLTableCellElement> & { numeric?: boolean };
export function TH({ numeric, className, children, ...rest }: ThProps) {
  return (
    <th
      className={cn(
        "px-3 h-8 font-mono uppercase text-[11px] font-medium tracking-[0.04em] text-ink-muted",
        numeric ? "text-right tabular" : "text-left",
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
  muted?: boolean;
};
export function TD({ numeric, mono, muted, className, children, ...rest }: TdProps) {
  return (
    <td
      className={cn(
        "px-3 align-middle text-[13px]",
        (numeric || mono) && "font-mono tabular",
        numeric && "text-right",
        muted && "text-ink-muted",
        className,
      )}
      {...rest}
    >
      {children}
    </td>
  );
}
