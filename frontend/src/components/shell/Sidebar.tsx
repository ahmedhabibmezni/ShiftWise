import {
  Home,
  Server,
  Monitor,
  ArrowLeftRight,
  Network,
  AlertTriangle,
  FileBarChart,
  Settings as SettingsIcon,
  Shield as ShieldIcon,
  Users as UsersIcon,
  LogOut,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useMutation } from "@tanstack/react-query";
import { NavLink } from "react-router-dom";
import { Icon } from "@/components/ui/Icon";
import { LiveIndicator } from "@/components/ui/LiveIndicator";
import { RoleBadge } from "@/components/ui/RoleBadge";
import { cn } from "@/lib/cn";
import { useAuthStore } from "@/store/auth";
import { hasPermission, primaryRole, type ResourceAction } from "@/lib/permissions";
import { logout as logoutRequest } from "@/api/auth";

type NavItem = {
  id: string;
  label: string;
  icon: LucideIcon;
  to?: string;
  badge?: number;
  badgeTone?: "signal" | "warn";
  /**
   * Permission requirement: the item is rendered only if the current user
   * holds the listed (resource, action). Items without a requirement are
   * shown to every signed-in user.
   */
  requires?: { resource: string; action: ResourceAction };
};

type NavSection = { kicker: string; items: NavItem[] };

const SECTIONS: NavSection[] = [
  {
    kicker: "monitoring",
    items: [
      { id: "overview", label: "overview", icon: Home, to: "/" },
      { id: "alerts", label: "alerts", icon: AlertTriangle, badge: 12, badgeTone: "warn" },
    ],
  },
  {
    kicker: "inventory",
    items: [
      {
        id: "hypervisors",
        label: "hypervisors",
        icon: Server,
        to: "/hypervisors",
        requires: { resource: "hypervisors", action: "read" },
      },
      {
        id: "vms",
        label: "virtual machines",
        icon: Monitor,
        to: "/vms",
        requires: { resource: "vms", action: "read" },
      },
      { id: "infrastructure", label: "infrastructure", icon: Network },
    ],
  },
  {
    kicker: "operations",
    items: [
      {
        id: "migrations",
        label: "migrations",
        icon: ArrowLeftRight,
        to: "/migrations",
        requires: { resource: "migrations", action: "read" },
      },
      {
        id: "reports",
        label: "reports",
        icon: FileBarChart,
        to: "/reports",
        requires: { resource: "reports", action: "read" },
      },
    ],
  },
  {
    kicker: "administration",
    items: [
      {
        id: "users",
        label: "users",
        icon: UsersIcon,
        to: "/users",
        requires: { resource: "users", action: "read" },
      },
      {
        id: "roles",
        label: "roles",
        icon: ShieldIcon,
        to: "/roles",
        requires: { resource: "roles", action: "read" },
      },
    ],
  },
  {
    kicker: "system",
    // Settings is universal — no `requires` so every signed-in user
    // (even a viewer) can reach their own profile + password rotation.
    items: [{ id: "settings", label: "settings", icon: SettingsIcon, to: "/settings" }],
  },
];

const ROW_CLASSES =
  "group relative flex items-center gap-3 h-9 pl-4 pr-3 transition-colors duration-150";

export function Sidebar() {
  const user = useAuthStore((s) => s.user);

  // Drop items the user has no permission to even *see*. An item with no
  // `requires` is treated as public. An item with `requires` is shown only
  // when the resource/action grant is present (super-users always pass).
  // Sections that become empty after filtering disappear entirely.
  const sections = SECTIONS.map((section) => ({
    ...section,
    items: section.items.filter(
      (item) =>
        !item.requires ||
        hasPermission(user, item.requires.resource, item.requires.action),
    ),
  })).filter((s) => s.items.length > 0);

  return (
    <aside
      aria-label="Primary navigation"
      className="w-[224px] shrink-0 bg-bg-elev border-r border-line flex flex-col"
    >
      <BrandHeader />
      <nav className="flex-1 overflow-y-auto py-2">
        {sections.map((section) => (
          <div key={section.kicker} className="pb-2 pt-3">
            <div className="kicker px-4 mb-1.5">{section.kicker}</div>
            <ul>
              {section.items.map((item) => (
                <li key={item.id}>
                  {item.to ? (
                    <NavLink
                      to={item.to}
                      end={item.to === "/"}
                      className={({ isActive }) =>
                        cn(
                          ROW_CLASSES,
                          isActive
                            ? "text-ink bg-bg-elev-2"
                            : "text-ink-muted hover:bg-bg-elev-2 hover:text-ink",
                        )
                      }
                    >
                      {({ isActive }) => <RowInner item={item} active={isActive} />}
                    </NavLink>
                  ) : (
                    <button
                      type="button"
                      disabled
                      aria-disabled
                      title="not yet available"
                      className={cn(
                        ROW_CLASSES,
                        "w-full text-ink-faint opacity-70 cursor-not-allowed",
                      )}
                    >
                      <RowInner item={item} active={false} disabled />
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>
      <ProfileFooter />
    </aside>
  );
}

function BrandHeader() {
  // The SW brand box swaps to the active role's accent. Subtle but the
  // colour change is on every page, so a viewer (blue) vs. an admin
  // (orange) vs. a super-admin (red) is recognisable from a peripheral
  // glance even when the role stripe is scrolled out of view on a
  // hypothetical full-screen page.
  return (
    <div className="h-14 px-4 flex items-center justify-between border-b border-line">
      <div className="flex items-center gap-2.5">
        <span
          aria-hidden
          className="relative inline-flex h-6 w-6 items-center justify-center text-signal-ink font-mono font-bold text-[11px]"
          style={{ backgroundColor: "var(--role-accent, var(--signal))" }}
        >
          SW
          <span
            aria-hidden
            className="absolute -bottom-1 -right-1 h-2 w-2 bg-bg-elev border border-line"
          />
        </span>
        <span className="flex flex-col leading-none">
          <span className="font-mono text-[12px] font-semibold tracking-[0.08em] text-ink">
            SHIFTWISE
          </span>
          <span className="font-mono text-[9px] uppercase tracking-[0.1em] text-ink-faint mt-0.5">
            console · v2.4
          </span>
        </span>
      </div>
    </div>
  );
}

function RowInner({
  item,
  active,
  disabled,
}: {
  item: NavItem;
  active: boolean;
  disabled?: boolean;
}) {
  const badgeColor = item.badgeTone === "warn" ? "var(--warn)" : "var(--signal)";
  return (
    <>
      {active && (
        <span
          aria-hidden
          className="absolute left-0 top-1.5 bottom-1.5 w-[2px] bg-signal"
        />
      )}
      <Icon icon={item.icon} size={16} className={disabled ? "opacity-60" : ""} />
      <span className="font-mono text-[12px] tracking-[0.02em] lowercase flex-1 truncate">
        {item.label}
      </span>
      {item.badge !== undefined && !disabled && (
        <span
          className="ml-auto inline-flex items-center justify-center min-w-[20px] h-[16px] px-1 rounded-sm font-mono text-[10px] font-semibold tabular"
          style={{
            color: badgeColor,
            backgroundColor: `color-mix(in srgb, ${badgeColor} 16%, transparent)`,
          }}
          aria-label={`${item.badge} notifications`}
        >
          {item.badge}
        </span>
      )}
    </>
  );
}

function getInitials(fullName: string | null | undefined, username: string): string {
  const source = (fullName ?? "").trim() || username;
  const parts = source.split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function ProfileFooter() {
  const user = useAuthStore((s) => s.user);
  const clearSession = useAuthStore((s) => s.clearSession);

  const logoutMutation = useMutation({
    mutationFn: logoutRequest,
    onSettled: () => clearSession(),
  });

  if (!user) return null;

  const initials = getInitials(user.full_name, user.username);
  const role = primaryRole(user);

  return (
    <div className="border-t border-line bg-bg-inset/40">
      <div className="px-3 py-2 flex items-center gap-2 border-b border-line">
        <LiveIndicator label={null} tone="ok" />
        <span className="font-mono text-[10px] uppercase tracking-[0.06em] text-ink-muted">
          cluster ok · 3/3 nodes
        </span>
      </div>
      <div className="px-3 py-3 flex items-center gap-3" aria-label="User profile">
        <span
          aria-hidden
          className="h-8 w-8 rounded-sm bg-bg-elev-2 border border-line-strong flex items-center justify-center font-mono text-[11px] font-semibold text-ink"
        >
          {initials}
        </span>
        <span className="flex-1 min-w-0 flex flex-col leading-tight gap-1">
          <span className="font-mono text-[12px] text-ink truncate">
            {user.username}
          </span>
          <RoleBadge role={role} />
        </span>
        <button
          type="button"
          onClick={() => logoutMutation.mutate()}
          disabled={logoutMutation.isPending}
          className="h-7 w-7 inline-flex items-center justify-center rounded-sm text-ink-muted hover:text-ink hover:bg-bg-elev-2 disabled:opacity-50 transition-colors duration-150 focus-visible:outline-1 focus-visible:outline-signal focus-visible:outline-offset-1"
          aria-label="Log out"
          title="Log out"
        >
          <Icon icon={LogOut} size={14} />
        </button>
      </div>
    </div>
  );
}
