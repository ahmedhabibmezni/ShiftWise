import type {
  HTMLAttributes,
  ReactNode,
  TdHTMLAttributes,
  ThHTMLAttributes,
} from "react";
import { cn } from "@/lib/cn";

export function Table({
  children,
  className,
  ...rest
}: HTMLAttributes<HTMLTableElement> & { children: ReactNode }) {
  return (
    <div className={cn("w-full overflow-x-auto", className)}>
      {/* Forward data-* and aria-* (and the rest of the standard HTML
          table attribute set) so callers can attach `data-testid` and
          assistive-tech hooks without us having to enumerate every
          prop here. */}
      <table className="w-full border-collapse" {...rest}>
        {children}
      </table>
    </div>
  );
}

export function THead({ children }: { children: ReactNode }) {
  return <thead>{children}</thead>;
}

type TrProps = HTMLAttributes<HTMLTableRowElement> & {
  interactive?: boolean;
};
export function TR({
  children,
  interactive,
  className,
  ...rest
}: TrProps) {
  return (
    <tr
      className={cn(
        "border-b border-[var(--hairline-faint)] last:border-b-0",
        interactive &&
          "transition-colors duration-200 hover:bg-[var(--surface-soft)] cursor-pointer",
        className,
      )}
      {...rest}
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
