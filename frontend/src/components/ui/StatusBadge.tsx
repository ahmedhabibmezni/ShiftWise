import type { LucideIcon } from "lucide-react";
import {
  CheckCircle2,
  AlertCircle,
  XCircle,
  PlayCircle,
  Clock,
  AlertTriangle,
  Loader2,
  Ban,
  RotateCcw,
} from "lucide-react";
import { cn } from "@/lib/cn";

type Tone = "ok" | "warn" | "err" | "signal" | "info" | "muted";

const TONE_PALETTE: Record<Tone, { bg: string; fg: string }> = {
  ok:     { bg: "rgba(1, 181, 116, 0.18)",  fg: "var(--alert-success-light)" },
  warn:   { bg: "rgba(232, 146, 42, 0.18)", fg: "var(--alert-high)" },
  err:    { bg: "rgba(224, 61, 61, 0.18)",  fg: "var(--alert-critical)" },
  signal: { bg: "rgba(230, 38, 0, 0.18)",   fg: "var(--accent-light)" },
  info:   { bg: "rgba(62, 111, 212, 0.18)", fg: "var(--blue-mid)" },
  muted:  { bg: "var(--surface-soft-strong)", fg: "var(--text-muted)" },
};

/**
 * Uppercase micro pill — matches `.status-chip` from base.css.
 * Used everywhere a status needs to communicate at a glance.
 *
 * `spin` turns the icon, signalling an in-flight state. It defaults on for
 * the `Loader2` glyph so a "Validating" / "Discovering" badge reads as
 * actively working rather than stalled.
 */
export function StatusBadge({
  icon: IconComponent,
  label,
  tone = "muted",
  spin,
  className,
}: {
  icon?: LucideIcon;
  label: string;
  tone?: Tone;
  spin?: boolean;
  className?: string;
}) {
  const palette = TONE_PALETTE[tone];
  const spinning = spin ?? IconComponent === Loader2;
  return (
    <span
      className={cn("status-chip tabular", className)}
      style={{ background: palette.bg, color: palette.fg }}
    >
      {IconComponent && (
        <IconComponent
          size={11}
          strokeWidth={2.25}
          className={spinning ? "sw-spin" : undefined}
        />
      )}
      {label}
    </span>
  );
}

export type MigrationStatusKey =
  | "PENDING"
  | "VALIDATING"
  | "PREPARING"
  | "TRANSFERRING"
  | "CONFIGURING"
  | "STARTING"
  | "VERIFYING"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED"
  | "ROLLBACK"
  | "ROLLED_BACK";

export type VmStatusKey =
  | "DISCOVERED"
  | "ANALYZING"
  | "COMPATIBLE"
  | "INCOMPATIBLE"
  | "PARTIAL"
  | "MIGRATING"
  | "MIGRATED"
  | "FAILED"
  | "ARCHIVED";

export type CompatibilityKey = "COMPATIBLE" | "PARTIAL" | "INCOMPATIBLE" | "UNKNOWN";

const MIGRATION_STATUS_MAP: Record<
  MigrationStatusKey,
  { label: string; tone: Tone; icon: LucideIcon }
> = {
  PENDING:      { label: "Pending",      tone: "muted",  icon: Clock },
  VALIDATING:   { label: "Validating",   tone: "info",   icon: Loader2 },
  PREPARING:    { label: "Preparing",    tone: "info",   icon: Loader2 },
  TRANSFERRING: { label: "Transferring", tone: "signal", icon: PlayCircle },
  CONFIGURING:  { label: "Configuring",  tone: "signal", icon: PlayCircle },
  STARTING:     { label: "Starting",     tone: "signal", icon: PlayCircle },
  VERIFYING:    { label: "Verifying",    tone: "signal", icon: Loader2 },
  COMPLETED:    { label: "Completed",    tone: "ok",     icon: CheckCircle2 },
  FAILED:       { label: "Failed",       tone: "err",    icon: XCircle },
  CANCELLED:    { label: "Cancelled",    tone: "muted",  icon: Ban },
  ROLLBACK:     { label: "Rolling Back", tone: "warn",   icon: RotateCcw },
  ROLLED_BACK:  { label: "Rolled Back",  tone: "warn",   icon: RotateCcw },
};

const COMPAT_MAP: Record<CompatibilityKey, { label: string; tone: Tone; icon: LucideIcon }> = {
  COMPATIBLE:   { label: "Compatible",   tone: "ok",   icon: CheckCircle2 },
  PARTIAL:      { label: "Partial",      tone: "warn", icon: AlertCircle },
  INCOMPATIBLE: { label: "Incompatible", tone: "err",  icon: XCircle },
  UNKNOWN:      { label: "Unknown",      tone: "muted", icon: AlertTriangle },
};

const VM_STATUS_MAP: Record<VmStatusKey, { label: string; tone: Tone; icon: LucideIcon }> = {
  DISCOVERED:   { label: "Discovered",   tone: "muted",  icon: Clock },
  ANALYZING:    { label: "Analyzing",    tone: "info",   icon: Loader2 },
  COMPATIBLE:   { label: "Compatible",   tone: "ok",     icon: CheckCircle2 },
  INCOMPATIBLE: { label: "Incompatible", tone: "err",    icon: XCircle },
  PARTIAL:      { label: "Partial",      tone: "warn",   icon: AlertCircle },
  MIGRATING:    { label: "Migrating",    tone: "signal", icon: PlayCircle },
  MIGRATED:     { label: "Migrated",     tone: "ok",     icon: CheckCircle2 },
  FAILED:       { label: "Failed",       tone: "err",    icon: XCircle },
  ARCHIVED:     { label: "Archived",     tone: "muted",  icon: Ban },
};

export function MigrationStatusBadge({
  status,
  className,
}: {
  status: MigrationStatusKey;
  className?: string;
}) {
  const map = MIGRATION_STATUS_MAP[status] ?? MIGRATION_STATUS_MAP.PENDING;
  return <StatusBadge icon={map.icon} label={map.label} tone={map.tone} className={className} />;
}

export function CompatibilityBadge({
  status,
  className,
}: {
  status: CompatibilityKey;
  className?: string;
}) {
  const map = COMPAT_MAP[status] ?? COMPAT_MAP.UNKNOWN;
  return <StatusBadge icon={map.icon} label={map.label} tone={map.tone} className={className} />;
}

export function VmStatusBadge({
  status,
  className,
}: {
  status: VmStatusKey;
  className?: string;
}) {
  const map = VM_STATUS_MAP[status] ?? VM_STATUS_MAP.DISCOVERED;
  return <StatusBadge icon={map.icon} label={map.label} tone={map.tone} className={className} />;
}

export type HypervisorStatusKey =
  | "active"
  | "inactive"
  | "error"
  | "unreachable"
  | "authenticating"
  | "discovering"
  | "unknown";

const HYPERVISOR_STATUS_MAP: Record<
  HypervisorStatusKey,
  { label: string; tone: Tone; icon: LucideIcon }
> = {
  active:         { label: "Active",         tone: "ok",   icon: CheckCircle2 },
  inactive:       { label: "Inactive",       tone: "muted", icon: Ban },
  error:          { label: "Error",          tone: "err",  icon: XCircle },
  unreachable:    { label: "Unreachable",    tone: "warn", icon: AlertTriangle },
  authenticating: { label: "Authenticating", tone: "info", icon: Loader2 },
  discovering:    { label: "Discovering",    tone: "info", icon: Loader2 },
  unknown:        { label: "Unknown",        tone: "warn", icon: AlertTriangle },
};

export function HypervisorStatusBadge({
  status,
  className,
}: {
  status: HypervisorStatusKey;
  className?: string;
}) {
  const map = HYPERVISOR_STATUS_MAP[status] ?? HYPERVISOR_STATUS_MAP.unknown;
  return <StatusBadge icon={map.icon} label={map.label} tone={map.tone} className={className} />;
}
