import {
  LayoutDashboard,
  Server,
  Monitor,
  ArrowRightLeft,
  BarChart3,
  Settings2,
  ShieldCheck,
  ServerCog,
  Users as UsersIcon,
  LogOut,
  LifeBuoy,
  ExternalLink,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useMutation } from "@tanstack/react-query";
import { NavLink } from "react-router-dom";
import { Icon } from "@/components/ui/Icon";
import { BrandLogo } from "@/components/ui/Logo";
import { RoleBadge } from "@/components/ui/RoleBadge";
import { cn } from "@/lib/cn";
import { useAuthStore } from "@/store/auth";
import { hasPermission, primaryRole, type ResourceAction } from "@/lib/permissions";
import { logout as logoutRequest } from "@/api/auth";
import { forceLogout } from "@/lib/session";

type NavItem = {
  id: string;
  label: string;
  icon: LucideIcon;
  to: string;
  requires?: { resource: string; action: ResourceAction };
};

type NavSection = { label?: string; items: NavItem[] };

const SECTIONS: NavSection[] = [
  {
    label: "Operations",
    items: [
      { id: "overview", label: "Dashboard", icon: LayoutDashboard, to: "/" },
      {
        id: "hypervisors",
        label: "Hypervisors",
        icon: Server,
        to: "/hypervisors",
        requires: { resource: "hypervisors", action: "read" },
      },
      {
        id: "vms",
        label: "Virtual Machines",
        icon: Monitor,
        to: "/vms",
        requires: { resource: "vms", action: "read" },
      },
      {
        id: "migrations",
        label: "Migrations",
        icon: ArrowRightLeft,
        to: "/migrations",
        requires: { resource: "migrations", action: "read" },
      },
      {
        id: "reports",
        label: "Reports",
        icon: BarChart3,
        to: "/reports",
        requires: { resource: "reports", action: "read" },
      },
    ],
  },
  {
    label: "Administration",
    items: [
      {
        id: "users",
        label: "Users",
        icon: UsersIcon,
        to: "/users",
        requires: { resource: "users", action: "read" },
      },
      {
        id: "roles",
        label: "Roles",
        icon: ShieldCheck,
        to: "/roles",
        requires: { resource: "roles", action: "read" },
      },
      {
        id: "infrastructure",
        label: "Infrastructure",
        icon: ServerCog,
        to: "/infrastructure",
        requires: { resource: "infrastructure", action: "read" },
      },
      { id: "settings", label: "Settings", icon: Settings2, to: "/settings" },
    ],
  },
];

/**
 * Desktop navigation rail — a sticky glass card, visible at `lg` and up.
 * Below `lg` the same content is rendered inside `MobileNav`'s overlay drawer.
 */
export function Sidebar() {
  return (
    <aside
      aria-label="Primary navigation"
      className="sidebar-rail sticky top-0 self-start hidden lg:flex flex-col w-[264px] shrink-0 overflow-hidden"
      style={{ height: "100dvh" }}
    >
      <SidebarBody />
    </aside>
  );
}

/**
 * The brand block, nav list, profile chip, and support card — shared verbatim
 * between the desktop `Sidebar` rail and the `MobileNav` drawer.
 *
 * @param onNavigate fired when a nav link is activated; the mobile drawer
 *        passes its close handler here so a tap dismisses the overlay.
 */
export function SidebarBody({ onNavigate }: { onNavigate?: () => void }) {
  const user = useAuthStore((s) => s.user);

  const sections = SECTIONS.map((section) => ({
    ...section,
    items: section.items.filter(
      (item) =>
        !item.requires ||
        hasPermission(user, item.requires.resource, item.requires.action),
    ),
  })).filter((s) => s.items.length > 0);

  return (
    <>
      {/* ---------- Brand ---------- */}
      <div className="relative z-[1] flex items-center px-4 pt-6 pb-4">
        <BrandLogo className="h-16" />
      </div>

      <div className="relative z-[1] mx-5 border-b border-[var(--hairline)]" />

      {/* ---------- Nav list ---------- */}
      <nav
        className="relative z-[1] flex-1 overflow-y-auto px-3 pt-4 pb-3"
        aria-label="Sections"
      >
        {sections.map((section, idx) => (
          <div
            key={section.label ?? idx}
            className={cn("flex flex-col", idx > 0 && "mt-6")}
          >
            {section.label && (
              <div className="px-3 mb-2.5 text-[11px] font-bold uppercase tracking-[0.1em] text-[var(--text-secondary)]">
                {section.label}
              </div>
            )}
            <ul className="flex flex-col gap-1">
              {section.items.map((item) => (
                <li key={item.id}>
                  <NavItemLink item={item} onNavigate={onNavigate} />
                </li>
              ))}
            </ul>
          </div>
        ))}
        {/* Support card sits just under the nav sections, in the scrollable
            upper region — not pinned to the rail floor with the profile. */}
        <div className="mt-6">
          <SupportCard />
        </div>
      </nav>

      {/* ---------- Profile ---------- */}
      <div className="relative z-[1] px-4 pb-4 pt-2 shrink-0">
        <ProfileChip />
      </div>
    </>
  );
}

function NavItemLink({
  item,
  onNavigate,
}: {
  item: NavItem;
  onNavigate?: () => void;
}) {
  return (
    <NavLink
      to={item.to}
      end={item.to === "/"}
      onClick={onNavigate}
      className={({ isActive }) =>
        cn(
          "group relative flex items-center gap-3 pl-3 pr-2.5 h-11 rounded-xl",
          "text-[14px] font-semibold transition-colors duration-150",
          isActive
            ? "text-[var(--text-primary)]"
            : "text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-soft)]",
        )
      }
      style={({ isActive }) =>
        isActive
          ? {
              background:
                "linear-gradient(135deg, rgba(230,38,0,0.18) 0%, rgba(255,122,47,0.10) 100%)",
              boxShadow: "inset 0 0 0 1px rgba(230,38,0,0.28)",
            }
          : undefined
      }
    >
      {({ isActive }) => (
        <>
          <span
            aria-hidden
            className={cn(
              "shrink-0 inline-flex items-center justify-center w-8 h-8 rounded-[10px] transition-all duration-150",
              isActive
                ? "icon-container icon-container--accent"
                : "bg-[var(--surface-soft-strong)] text-[var(--accent-light)] group-hover:bg-[var(--surface-soft-strong)]",
            )}
          >
            <Icon icon={item.icon} size={16} strokeWidth={1.75} />
          </span>
          <span className="flex-1 truncate">{item.label}</span>
        </>
      )}
    </NavLink>
  );
}

function ProfileChip() {
  const user = useAuthStore((s) => s.user);
  // `forceLogout` clears the auth store, purges the query cache, and
  // redirects to /login — whether the server logout request succeeds
  // or fails (network error, 5xx).
  const logoutMutation = useMutation({
    mutationFn: logoutRequest,
    onSettled: () => forceLogout(),
  });

  if (!user) return null;
  const role = primaryRole(user);
  const initials = getInitials(user.full_name, user.username);
  const displayName = user.full_name?.trim() || user.username;

  return (
    <div
      className="flex items-center gap-3 px-3 py-3 rounded-card bg-[var(--surface-soft-strong)] border border-[var(--line-strong)]"
      style={{ boxShadow: "var(--shadow-card)" }}
    >
      <span
        aria-hidden
        className="grid place-items-center w-10 h-10 rounded-full text-white text-[13px] font-bold shrink-0"
        style={{
          background:
            "linear-gradient(135deg, var(--accent-primary), var(--accent-light))",
          boxShadow: "var(--shadow-accent), 0 0 0 3px var(--accent-tint)",
        }}
      >
        {initials}
      </span>
      <div className="flex-1 min-w-0 flex flex-col leading-tight gap-1.5">
        <span className="text-[14px] font-bold tracking-[-0.01em] text-[var(--text-primary)] truncate">
          {displayName}
        </span>
        <RoleBadge role={role} />
      </div>
      <button
        type="button"
        onClick={() => logoutMutation.mutate()}
        disabled={logoutMutation.isPending}
        className="shrink-0 h-8 w-8 inline-flex items-center justify-center rounded-[12px] text-[var(--text-muted)] hover:text-[var(--accent-light)] hover:bg-[var(--surface-soft-strong)] transition-colors duration-200 disabled:opacity-50"
        aria-label="Log out"
        title="Log out"
      >
        <LogOut size={15} strokeWidth={1.75} />
      </button>
    </div>
  );
}

function SupportCard() {
  return (
    <div
      className="relative overflow-hidden rounded-card p-4"
      style={{
        background: "var(--sidebar-card-gradient)",
        boxShadow: "0 6px 24px rgba(31, 63, 138, 0.35)",
      }}
    >
      <span
        aria-hidden
        className="absolute inset-0 pointer-events-none"
        style={{
          background:
            "radial-gradient(circle at 85% 0%, rgba(255, 122, 47, 0.42), transparent 58%)",
        }}
      />
      <div className="relative z-[1] flex flex-col gap-3">
        <div className="flex items-center gap-2.5">
          <span
            className="inline-flex items-center justify-center w-8 h-8 rounded-[10px] text-white shrink-0"
            style={{ background: "rgba(255, 255, 255, 0.18)" }}
          >
            <LifeBuoy size={16} strokeWidth={2} />
          </span>
          <span className="text-[13px] font-bold text-white leading-tight">
            Need help?
          </span>
        </div>
        <a
          href="https://docs.openshift.com/container-platform/4.18/virt/about-virt.html"
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center justify-center gap-1.5 w-full text-[12px] font-bold text-[#0F1535] bg-white/95 hover:bg-white px-3 py-2 rounded-[12px] transition-colors duration-200"
        >
          Documentation
          <ExternalLink size={12} strokeWidth={2} />
        </a>
      </div>
    </div>
  );
}

function getInitials(fullName: string | null | undefined, username: string): string {
  const source = (fullName ?? "").trim() || username;
  const parts = source.split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}
