import type { ReactNode, ThHTMLAttributes, TdHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

export function Table({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("w-full overflow-x-auto", className)}>
      <table className="w-full border-collapse">{children}</table>
    </div>
  );
}

export function THead({ children }: { children: ReactNode }) {
  return <thead>{children}</thead>;
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
        "border-b border-[var(--hairline-faint)] last:border-b-0",
        interactive &&
          "transition-colors duration-200 hover:bg-[var(--surface-soft)] cursor-pointer",
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
        "px-3 py-3 uppercase text-[10px] font-bold tracking-[0.04em] text-[var(--text-muted)]",
        "border-b border-[var(--hairline)]",
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
        "px-3 py-3.5 align-middle text-[13px] text-[var(--text-primary)]",
        (numeric || mono) && "tabular",
        numeric && "text-right",
        mono && "font-mono text-[12px]",
        muted && "text-[var(--text-secondary)]",
        className,
      )}
      {...rest}
    >
      {children}
    </td>
  );
}
