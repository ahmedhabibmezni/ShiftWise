import { Crown, Eye, Shield, ShieldCheck } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Icon } from "@/components/ui/Icon";
import { cn } from "@/lib/cn";

const ROLE_META: Record<
  string,
  { label: string; icon: LucideIcon; color: string; bg: string }
> = {
  super_admin: {
    label: "super admin",
    icon: Crown,
    color: "var(--err)",
    bg: "color-mix(in srgb, var(--err) 14%, transparent)",
  },
  admin: {
    label: "admin",
    icon: ShieldCheck,
    color: "var(--signal)",
    bg: "color-mix(in srgb, var(--signal) 14%, transparent)",
  },
  user: {
    label: "user",
    icon: Shield,
    color: "var(--ok)",
    bg: "color-mix(in srgb, var(--ok) 14%, transparent)",
  },
  viewer: {
    label: "viewer",
    icon: Eye,
    color: "var(--info)",
    bg: "color-mix(in srgb, var(--info) 14%, transparent)",
  },
};

const FALLBACK = {
  label: "—",
  icon: Shield,
  color: "var(--ink-muted)",
  bg: "color-mix(in srgb, var(--ink-muted) 14%, transparent)",
};

export function RoleBadge({
  role,
  className,
  compact,
}: {
  role: string | null;
  className?: string;
  compact?: boolean;
}) {
  const meta = (role && ROLE_META[role]) || FALLBACK;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 px-2 h-6 rounded-sm",
        "font-mono uppercase text-[10px] font-semibold tracking-[0.06em] tabular",
        "border border-transparent",
        className,
      )}
      style={{ color: meta.color, backgroundColor: meta.bg }}
      aria-label={`Role: ${meta.label}`}
      title={`Role: ${meta.label}`}
    >
      <Icon icon={meta.icon} size={14} />
      {!compact && <span>{meta.label}</span>}
    </span>
  );
}
