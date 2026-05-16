import { Crown, Eye, Shield, ShieldCheck } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Icon } from "@/components/ui/Icon";
import { cn } from "@/lib/cn";

const ROLE_META: Record<
  string,
  { label: string; icon: LucideIcon; color: string; bg: string }
> = {
  super_admin: {
    label: "Super Admin",
    icon: Crown,
    color: "var(--alert-critical)",
    bg: "rgba(224, 61, 61, 0.16)",
  },
  admin: {
    label: "Admin",
    icon: ShieldCheck,
    color: "var(--accent-light)",
    bg: "rgba(230, 38, 0, 0.16)",
  },
  user: {
    label: "User",
    icon: Shield,
    color: "var(--alert-success-light)",
    bg: "rgba(1, 181, 116, 0.16)",
  },
  viewer: {
    label: "Viewer",
    icon: Eye,
    color: "var(--blue-mid)",
    bg: "rgba(62, 111, 212, 0.16)",
  },
};

const FALLBACK = {
  label: "—",
  icon: Shield,
  color: "var(--text-muted)",
  bg: "var(--surface-soft-strong)",
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
        "inline-flex items-center gap-1.5 px-2.5 h-6 rounded-full",
        "uppercase text-[10px] font-bold tracking-[0.04em] tabular",
        className,
      )}
      style={{ color: meta.color, backgroundColor: meta.bg }}
      aria-label={`Role: ${meta.label}`}
      title={`Role: ${meta.label}`}
    >
      <Icon icon={meta.icon} size={11} strokeWidth={2.25} />
      {!compact && <span>{meta.label}</span>}
    </span>
  );
}
