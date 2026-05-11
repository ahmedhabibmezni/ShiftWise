import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Lock,
  Plus,
  Search,
  Shield,
  ShieldCheck,
  Sparkles,
  Users as UsersIcon,
} from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { EmptyState } from "@/components/ui/EmptyState";
import { Icon } from "@/components/ui/Icon";
import { Input } from "@/components/ui/Input";
import { Panel } from "@/components/ui/Panel";
import { PageHeader } from "@/components/ui/PageHeader";
import { Skeleton, SkeletonRow } from "@/components/ui/Skeleton";
import { Table, TD, TH, THead, TR } from "@/components/ui/Table";
import { formatNumber, formatRelativeTime } from "@/lib/format";
import { useHasPermission } from "@/lib/permissions";
import {
  getRolesCount,
  listRoles,
  type RoleDetail,
} from "@/api/roles";
import { RoleCreateDrawer } from "./RoleCreateDrawer";
import { RoleDetailDrawer } from "./RoleDetailDrawer";

const REFETCH_MS = 60_000;

function permissionsSummary(perms: Record<string, string[]>): string {
  const entries = Object.entries(perms);
  if (entries.length === 0) return "no permissions";
  const granted = entries.filter(([, v]) => v.length > 0).length;
  return `${granted} resource${granted > 1 ? "s" : ""}`;
}

function wildcardCount(perms: Record<string, string[]>): number {
  return Object.values(perms).filter((v) => v.includes("*")).length;
}

export default function Roles() {
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const canCreate = useHasPermission("roles", "create");

  const listQuery = useQuery({
    queryKey: ["roles", "list", search],
    queryFn: () => listRoles({ limit: 200, ...(search.trim() ? { search: search.trim() } : {}) }),
    refetchInterval: REFETCH_MS,
  });

  const countQuery = useQuery({
    queryKey: ["roles", "count"],
    queryFn: () => getRolesCount(),
    refetchInterval: REFETCH_MS,
  });

  const roles = useMemo(() => listQuery.data ?? [], [listQuery.data]);
  const activeRoles = roles.filter((r) => r.is_active).length;
  const inactiveRoles = roles.length - activeRoles;

  return (
    <div className="max-w-[1440px] mx-auto p-6 md:p-8 space-y-6">
      <PageHeader
        kicker="administration"
        title="roles"
        breadcrumbs={[{ label: "console" }, { label: "administration" }, { label: "roles" }]}
        description="Role-based access control · system roles are immutable, custom roles are tenant-editable."
        actions={
          canCreate ? (
            <Button
              variant="primary"
              uppercase
              leadingIcon={<Icon icon={Plus} size={16} />}
              onClick={() => setCreateOpen(true)}
            >
              new role
            </Button>
          ) : null
        }
      />

      <StatsStrip
        total={countQuery.data?.total}
        system={countQuery.data?.system_roles}
        custom={countQuery.data?.custom_roles}
        inactive={inactiveRoles}
        isLoading={countQuery.isPending}
      />

      <Panel
        density="compact"
        kicker={`${roles.length} roles in catalogue`}
        title="permission sets"
        action={
          <div className="relative">
            <Icon
              icon={Search}
              size={14}
              className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-faint pointer-events-none"
            />
            <Input
              aria-label="Search roles"
              placeholder="name or description…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-8 h-9 w-52"
            />
          </div>
        }
        bodyClassName="px-0"
      >
        <RoleTable
          roles={roles}
          isLoading={listQuery.isPending}
          isError={listQuery.isError}
          onRowClick={(id) => setSelectedId(id)}
          canCreate={canCreate}
          onCreate={() => setCreateOpen(true)}
        />
      </Panel>

      <RoleDetailDrawer id={selectedId} onClose={() => setSelectedId(null)} />
      <RoleCreateDrawer open={createOpen} onClose={() => setCreateOpen(false)} />
    </div>
  );
}

/* ------------------------------- stats strip ------------------------------ */

function StatsStrip({
  total,
  system,
  custom,
  inactive,
  isLoading,
}: {
  total: number | undefined;
  system: number | undefined;
  custom: number | undefined;
  inactive: number;
  isLoading: boolean;
}) {
  return (
    <section className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      <Tile
        kicker="total"
        value={isLoading ? null : formatNumber(total)}
        tone="signal"
        icon={Shield}
      />
      <Tile
        kicker="system"
        value={isLoading ? null : formatNumber(system)}
        hint="immutable · seeded at install"
        tone="muted"
        icon={Lock}
      />
      <Tile
        kicker="custom"
        value={isLoading ? null : formatNumber(custom)}
        hint="tenant-defined · editable"
        tone="ok"
        icon={Sparkles}
      />
      <Tile
        kicker="inactive"
        value={isLoading ? null : formatNumber(inactive)}
        tone={inactive > 0 ? "warn" : "muted"}
      />
    </section>
  );
}

function Tile({
  kicker,
  value,
  hint,
  tone,
  icon,
}: {
  kicker: string;
  value: string | null;
  hint?: string;
  tone: "ok" | "warn" | "muted" | "signal";
  icon?: typeof Shield;
}) {
  const color =
    tone === "ok"
      ? "var(--ok)"
      : tone === "warn"
        ? "var(--warn)"
        : tone === "signal"
          ? "var(--signal)"
          : "var(--ink)";
  return (
    <Panel density="compact">
      <div className="flex items-start justify-between gap-3">
        <span className="kicker">{kicker}</span>
        {icon && <Icon icon={icon} size={14} className="text-ink-faint" />}
      </div>
      <div className="mt-2 flex items-baseline gap-2">
        {value === null ? (
          <Skeleton className="h-7 w-20" />
        ) : (
          <span className="font-mono tabular text-[28px] leading-none" style={{ color }}>
            {value}
          </span>
        )}
      </div>
      {hint && (
        <div className="mt-2 font-mono text-[10px] uppercase tracking-[0.06em] text-ink-faint truncate">
          {hint}
        </div>
      )}
    </Panel>
  );
}

/* --------------------------------- table ---------------------------------- */

function RoleTable({
  roles,
  isLoading,
  isError,
  onRowClick,
  canCreate,
  onCreate,
}: {
  roles: RoleDetail[];
  isLoading: boolean;
  isError: boolean;
  onRowClick: (id: number) => void;
  canCreate: boolean;
  onCreate: () => void;
}) {
  if (isError) {
    return (
      <div className="m-6">
        <Callout tone="err" role="alert">
          failed to load roles.
        </Callout>
      </div>
    );
  }

  if (isLoading && roles.length === 0) {
    return (
      <div className="px-6 pb-5">
        {Array.from({ length: 4 }).map((_, i) => (
          <SkeletonRow key={i} cols={6} />
        ))}
      </div>
    );
  }

  if (roles.length === 0) {
    return (
      <EmptyState
        icon={Shield}
        title="no roles"
        hint={
          canCreate
            ? "no role matches your search — create a custom one to scope permissions."
            : "no roles match your search."
        }
        action={
          canCreate ? (
            <Button
              variant="primary"
              uppercase
              leadingIcon={<Icon icon={Plus} size={14} />}
              onClick={onCreate}
            >
              new role
            </Button>
          ) : undefined
        }
      />
    );
  }

  return (
    <div className="overflow-x-auto">
      <Table className="border-0">
        <THead>
          <TR>
            <TH>name</TH>
            <TH>description</TH>
            <TH>scope</TH>
            <TH>permissions</TH>
            <TH>status</TH>
            <TH numeric>updated</TH>
          </TR>
        </THead>
        <tbody>
          {roles.map((r, i) => (
            <TR key={r.id} interactive className="sw-mount">
              <TD>
                <button
                  type="button"
                  onClick={() => onRowClick(r.id)}
                  className="text-left hover:text-signal transition-colors duration-150 w-full font-medium flex items-center gap-2"
                  style={{ "--sw-i": i } as React.CSSProperties}
                >
                  <Icon
                    icon={r.is_system_role ? Lock : ShieldCheck}
                    size={13}
                    className={r.is_system_role ? "text-ink-faint" : "text-ok"}
                  />
                  {r.name}
                </button>
              </TD>
              <TD muted>{r.description ?? "—"}</TD>
              <TD>
                <Badge variant={r.is_system_role ? "info" : "ok"}>
                  {r.is_system_role ? "system" : "custom"}
                </Badge>
              </TD>
              <TD mono muted>
                <span className="inline-flex items-center gap-2">
                  <span className="inline-flex items-center gap-1">
                    <Icon icon={UsersIcon} size={11} className="text-ink-faint" />
                    {permissionsSummary(r.permissions)}
                  </span>
                  {wildcardCount(r.permissions) > 0 && (
                    <span
                      className="font-mono text-[10px] uppercase tracking-[0.05em]"
                      style={{ color: "var(--signal)" }}
                      title="wildcard grants"
                    >
                      · {wildcardCount(r.permissions)}×*
                    </span>
                  )}
                </span>
              </TD>
              <TD>
                <Badge variant={r.is_active ? "ok" : "neutral"}>
                  {r.is_active ? "active" : "disabled"}
                </Badge>
              </TD>
              <TD numeric muted>
                {formatRelativeTime(r.updated_at)}
              </TD>
            </TR>
          ))}
        </tbody>
      </Table>
    </div>
  );
}
