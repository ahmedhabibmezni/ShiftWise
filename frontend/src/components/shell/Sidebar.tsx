import {
  Home,
  Server,
  Monitor,
  ArrowLeftRight,
  Network,
  AlertTriangle,
  FileBarChart,
  Settings as SettingsIcon,
  LogOut,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useMutation } from "@tanstack/react-query";
import { NavLink } from "react-router-dom";
import { Icon } from "@/components/ui/Icon";
import { cn } from "@/lib/cn";
import { useAuthStore } from "@/store/auth";
import { logout as logoutRequest } from "@/api/auth";

type NavItem = {
  id: string;
  label: string;
  icon: LucideIcon;
  to?: string;
  badge?: number;
};

const ITEMS: NavItem[] = [
  { id: "overview", label: "overview", icon: Home, to: "/" },
  { id: "hypervisors", label: "hypervisors", icon: Server, to: "/hypervisors" },
  { id: "vms", label: "vms", icon: Monitor, to: "/vms" },
  { id: "migrations", label: "migrations", icon: ArrowLeftRight },
  { id: "infrastructure", label: "infrastructure", icon: Network },
  { id: "alerts", label: "alerts", icon: AlertTriangle, badge: 12 },
  { id: "reports", label: "reports", icon: FileBarChart },
  { id: "settings", label: "settings", icon: SettingsIcon },
];

const ITEM_CLASSES =
  "relative w-full h-16 flex flex-col items-center justify-center gap-1.5 transition-colors duration-150";

export function Sidebar() {
  return (
    <aside
      aria-label="Navigation principale"
      className="w-20 shrink-0 bg-bg-elev border-r border-line-strong flex flex-col"
    >
      <div className="h-16 w-full flex items-center justify-center border-b border-line">
        <div className="font-mono uppercase font-bold text-[20px] tracking-[0.04em] text-ink">
          SW
        </div>
      </div>

      <nav className="flex-1 py-2">
        <ul>
          {ITEMS.map((item) => (
            <li key={item.id}>
              {item.to ? (
                <NavLink
                  to={item.to}
                  end={item.to === "/"}
                  className={({ isActive }) =>
                    cn(
                      ITEM_CLASSES,
                      isActive
                        ? "text-signal"
                        : "text-ink-muted hover:bg-bg-elev-2 hover:text-ink",
                    )
                  }
                >
                  {({ isActive }) => <NavItemInner item={item} active={isActive} />}
                </NavLink>
              ) : (
                <button
                  type="button"
                  disabled
                  aria-disabled
                  title="Bientôt disponible"
                  className={cn(
                    ITEM_CLASSES,
                    "text-ink-muted opacity-50 cursor-not-allowed",
                  )}
                >
                  <NavItemInner item={item} active={false} />
                </button>
              )}
            </li>
          ))}
        </ul>
      </nav>

      <ProfileFooter />
    </aside>
  );
}

function NavItemInner({ item, active }: { item: NavItem; active: boolean }) {
  return (
    <>
      {active && (
        <span
          aria-hidden
          className="absolute left-0 top-2 bottom-2 w-0.5 bg-signal"
        />
      )}
      <span className="relative">
        <Icon icon={item.icon} size={20} />
        {item.badge && (
          <span
            className="absolute -top-1.5 -right-2.5 min-w-[18px] h-[18px] px-1 rounded-full bg-signal text-signal-ink font-mono text-[10px] font-medium tabular flex items-center justify-center"
            aria-label={`${item.badge} alertes`}
          >
            {item.badge}
          </span>
        )}
      </span>
      <span className="font-mono text-[10px] uppercase tracking-[0.04em]">
        {item.label}
      </span>
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

function primaryRole(roleNames: string[]): string {
  const order = ["super_admin", "admin", "user", "viewer"];
  for (const r of order) if (roleNames.includes(r)) return r;
  return roleNames[0] ?? "—";
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
  const role = user.is_superuser
    ? "super_admin"
    : primaryRole(user.roles.map((r) => r.name));

  return (
    <div className="border-t border-line">
      <div className="h-20 px-3 flex items-center gap-3" aria-label="Profil utilisateur">
        <span
          aria-hidden
          className="h-8 w-8 rounded-sm bg-bg-elev-2 border border-line-strong flex items-center justify-center font-mono text-[12px] font-semibold text-ink"
        >
          {initials}
        </span>
        <span className="flex-1 min-w-0">
          <span className="block font-mono text-[11px] uppercase text-ink truncate">
            {user.username}
          </span>
          <span className="block font-mono text-[10px] uppercase text-ink-muted truncate">
            {role}
          </span>
        </span>
        <button
          type="button"
          onClick={() => logoutMutation.mutate()}
          disabled={logoutMutation.isPending}
          className="text-ink-muted hover:text-ink disabled:opacity-50 transition-colors duration-150"
          aria-label="Se déconnecter"
          title="Se déconnecter"
        >
          <Icon icon={LogOut} size={16} />
        </button>
      </div>
    </div>
  );
}
