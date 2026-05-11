import { Icon } from "@/components/ui/Icon";
import { usePrimaryRole } from "@/lib/permissions";
import { getRoleTheme } from "@/lib/role-theme";
import { useAuthStore } from "@/store/auth";

/**
 * A high-visibility banner mounted under the Header on every authenticated
 * page. The role-coloured left border + tinted background + bold uppercase
 * label make the operator's current privilege level impossible to miss —
 * "what can I do here right now?" is answered before reading anything else.
 */
export function RoleStripe() {
  const user = useAuthStore((s) => s.user);
  const role = usePrimaryRole();
  if (!user) return null;

  const theme = getRoleTheme(role);
  const displayName = user.full_name?.trim() || user.username;

  return (
    <div
      role="region"
      aria-label="Current operator role"
      data-role={theme.role}
      className="border-b border-line"
      style={{
        backgroundColor: theme.accentBg,
        borderLeft: `3px solid ${theme.accentColor}`,
      }}
    >
      <div className="max-w-[1440px] mx-auto px-6 md:px-8 py-2.5 flex items-center gap-4 flex-wrap">
        <span
          className="inline-flex items-center gap-2"
          style={{ color: theme.accentColor }}
        >
          <Icon icon={theme.icon} size={16} />
          <span className="font-mono text-[11px] uppercase tracking-[0.1em] font-bold">
            {theme.label}
          </span>
        </span>

        <span aria-hidden className="h-4 w-px bg-line shrink-0" />

        <span className="font-mono text-[12px] text-ink truncate">
          {displayName}
        </span>

        <span className="font-mono text-[11px] text-ink-muted truncate">
          tenant · {user.tenant_id}
        </span>

        <span
          aria-hidden
          className="hidden md:inline-block h-4 w-px bg-line shrink-0"
        />
        <span className="hidden md:inline-block font-mono text-[11px] text-ink-muted truncate flex-1 min-w-0">
          {theme.capabilities}
        </span>

        <span
          className="ml-auto md:ml-0 font-mono text-[10px] uppercase tracking-[0.06em] px-2 py-0.5 rounded-sm"
          style={{
            color: theme.accentColor,
            backgroundColor: theme.accentTint,
          }}
        >
          {theme.description}
        </span>
      </div>
    </div>
  );
}
