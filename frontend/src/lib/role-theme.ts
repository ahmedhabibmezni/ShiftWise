import { Crown, Eye, Shield, ShieldCheck } from "lucide-react";
import type { LucideIcon } from "lucide-react";

export type RoleTheme = {
  role: string;
  label: string;
  icon: LucideIcon;
  /** Solid CSS color used for icons, labels, strong accents. */
  accentColor: string;
  /** Tinted background derived from accentColor (used on the stripe). */
  accentBg: string;
  /** Tinted background derived from accentColor (used for surfaces). */
  accentTint: string;
  /** Short noun for the role's privilege level. */
  description: string;
  /** One-line summary of what the user is allowed to do. */
  capabilities: string;
};

const make = (
  color: string,
  label: string,
  icon: LucideIcon,
  description: string,
  capabilities: string,
  role: string,
): RoleTheme => ({
  role,
  label,
  icon,
  accentColor: color,
  // The bg is opaque to remain readable on every theme — we mix the role
  // color with the page background instead of using transparency, which
  // can clash with stacked banners or screenshots.
  accentBg: `color-mix(in srgb, ${color} 12%, var(--bg))`,
  accentTint: `color-mix(in srgb, ${color} 18%, transparent)`,
  description,
  capabilities,
});

export const ROLE_THEMES: Record<string, RoleTheme> = {
  super_admin: make(
    "var(--err)",
    "SUPER ADMIN",
    Crown,
    "Root access",
    "All tenants · every action · cannot be revoked from the UI",
    "super_admin",
  ),
  admin: make(
    "var(--signal)",
    "ADMINISTRATOR",
    ShieldCheck,
    "Tenant administrator",
    "Hypervisors · VMs · migrations · users — full control on this tenant",
    "admin",
  ),
  user: make(
    "var(--ok)",
    "USER",
    Shield,
    "Standard operator",
    "Browse · analyze VMs · trigger migrations on this tenant",
    "user",
  ),
  viewer: make(
    "var(--info)",
    "VIEWER",
    Eye,
    "Read-only",
    "Browse only — no write actions, no analyzer trigger",
    "viewer",
  ),
};

const FALLBACK_THEME = make(
  "var(--ink-muted)",
  "MEMBER",
  Shield,
  "Member",
  "—",
  "—",
);

export function getRoleTheme(roleName: string | null | undefined): RoleTheme {
  if (!roleName) return FALLBACK_THEME;
  return ROLE_THEMES[roleName] ?? FALLBACK_THEME;
}
