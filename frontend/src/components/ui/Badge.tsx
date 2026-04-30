import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export type BadgeVariant = "ok" | "partial" | "incompatible" | "info" | "warn" | "neutral";

const dotColor: Record<BadgeVariant, string> = {
  ok: "bg-ok",
  partial: "bg-warn",
  incompatible: "bg-err",
  info: "bg-info",
  warn: "bg-warn",
  neutral: "bg-ink-muted",
};

type Props = {
  variant?: BadgeVariant;
  children: ReactNode;
  className?: string;
};

export function Badge({ variant = "neutral", children, className }: Props) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 h-5 px-1.5 border border-line rounded-sm",
        "font-mono text-[11px] uppercase tracking-[0.05em] leading-none text-ink",
        className,
      )}
    >
      <span className={cn("inline-block h-1.5 w-1.5", dotColor[variant])} />
      {children}
    </span>
  );
}
